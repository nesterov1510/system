#!/usr/bin/env bash
# MSB — пересборка и перезапуск системы после изменения файлов.
#
# Скрипт не скачивает сам проект: он собирает то, что уже лежит на диске,
# и перезапускает сервисы от имени администратора (root).
#
# Запуск (на сервере):
#   cd /home/windowrepair-ae/msb
#   sudo bash deploy/update.sh              # api + print-agent (если установлен)
#   sudo bash deploy/update.sh --api-only   # только api, агента не трогать
#
# Что делает:
#   1) проверяет .venv каждого сервиса: python внутри должен реально
#      запускаться и иметь pip. Сломанный venv (типичный случай — обновление
#      системного Python в ОС, после которого systemd падает с
#      «status=203/EXEC») ПЕРЕСОЗДАЁТСЯ автоматически;
#   2) ставит зависимости из requirements.txt;
#   3) перезапускает msb-api, а также msb-print-agent — если его unit
#      установлен И (включён / запущен / упал). Агент, который админ
#      сознательно выключил (disabled + inactive), не трогаем;
#   4) сверяет путь ExecStart в unit-файле с реальным MSB_ROOT и после
#      перезапуска ловит restart-loop (мгновенное падение сервиса).
#
# Права администратора запрашиваются сами (sudo). Каталог проекта берётся
# из MSB_ROOT (по умолчанию — родительский каталог этого скрипта),
# порт API — из MSB_API_PORT (по умолчанию 8085).

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${MSB_ROOT:-$(dirname "$SCRIPT_DIR")}"
API_PORT="${MSB_API_PORT:-8085}"
AGENT_ONLY_SKIP=0   # --api-only: print-agent не трогаем совсем

for arg in "$@"; do
  case "$arg" in
    --web-only)
      echo "Отдельного фронтенда больше нет (Jinja2 UI отдаёт API на :$API_PORT)."
      echo "Используйте: sudo bash deploy/update.sh"
      exit 0
      ;;
    --api-only) AGENT_ONLY_SKIP=1 ;;
    -h|--help) sed -n '2,26p' "$0"; exit 0 ;;
    *) echo "Неизвестный аргумент: $arg"; exit 2 ;;
  esac
done

RED=$'\e[31m'; GRN=$'\e[32m'; YLW=$'\e[33m'; BLD=$'\e[1m'; RST=$'\e[0m'
step() { echo; echo "${BLD}==> $*${RST}"; }
ok()   { echo "${GRN}  ✓ $*${RST}"; }
warn() { echo "${YLW}  ! $*${RST}"; }
err()  { echo "${RED}  ✗ $*${RST}"; }
die()  { err "$*"; exit 1; }

# ------------------------------------------------- права администратора
if [ "$(id -u)" -eq 0 ]; then
  SUDO=""
else
  command -v sudo >/dev/null 2>&1 || die "нужны права администратора: запустите 'sudo bash deploy/update.sh'"
  SUDO="sudo"
  # Спросить пароль один раз в начале, а не посреди перезапуска сервисов.
  sudo -v || die "не удалось получить права администратора (sudo)"
fi

have_systemd() { command -v systemctl >/dev/null 2>&1; }

# Состояние юнита: active/activating/failed/inactive (пусто, если нет systemd).
unit_state() {
  have_systemd || return 0
  $SUDO systemctl is-active "$1" 2>/dev/null || true
}

unit_enabled() {
  have_systemd || return 1
  $SUDO systemctl is-enabled --quiet "$1" 2>/dev/null
}

unit_installed() {
  have_systemd || return 1
  $SUDO systemctl cat "$1" >/dev/null 2>&1
}

restart_unit() {
  local unit="$1" grace="${2:-2}"
  if ! have_systemd; then warn "systemctl нет — пропускаю перезапуск $unit"; return 0; fi
  $SUDO systemctl restart "$unit" || die "не удалось перезапустить $unit"
  sleep "$grace"
  if $SUDO systemctl is-active --quiet "$unit"; then
    ok "$unit перезапущен"
  else
    echo "${RED}--- journalctl -u $unit -n 40 ---${RST}"
    $SUDO journalctl -u "$unit" -n 40 --no-pager
    die "$unit не поднялся (лог выше)"
  fi
}

echo "${BLD}MSB update${RST}  root=$ROOT  api:$API_PORT"
[ -d "$ROOT/apps/api" ] || die "не найден $ROOT/apps/api — задайте MSB_ROOT=/путь/к/msb"

# Владелец каталога проекта: под root собираем от его имени, чтобы файлы
# не стали root-овыми и следующий запуск без sudo не сломался.
OWNER="$(stat -c '%U' "$ROOT/apps/api")"
run_as_owner() {
  if [ "$(id -u)" -eq 0 ] && [ "$OWNER" != "root" ] && command -v runuser >/dev/null 2>&1; then
    runuser -u "$OWNER" -- "$@"
  else
    "$@"
  fi
}

# ------------------------------------------------------------------ venv
# venv «здоров», только если его python реально запускается и в нём есть pip.
# Одного [ -x .venv/bin/python ] мало: после обновления системного Python
# симлинк может указывать в никуда → systemd падает с 203/EXEC.
venv_ok() {
  local venv="$1"
  [ -x "$venv/bin/python" ] || return 1
  run_as_owner "$venv/bin/python" -V >/dev/null 2>&1 || return 1
  [ -x "$venv/bin/pip" ] || return 1
  run_as_owner "$venv/bin/python" -m pip --version >/dev/null 2>&1 || return 1
  return 0
}

# ensure_venv <appdir> → вернёт 0 и выставит FRESH_VENV=1, если venv
# пришлось создать заново (значит, pip install обязателен).
FRESH_VENV=0
ensure_venv() {
  # NB: не объединять «local a=.. b=$a/..» в одну строку — под «set -u»
  # $a раскрывается до того, как local его присвоит (unbound variable).
  local appdir="$1"
  local venv="$appdir/.venv"
  FRESH_VENV=0
  if venv_ok "$venv"; then
    ok "$venv в порядке"
    return 0
  fi
  if [ -e "$venv" ] || [ -L "$venv" ]; then
    warn "$venv повреждён или не запускается — пересоздаю (обычно это следствие обновления системного Python)"
    case "$venv" in
      */.venv) rm -rf -- "$venv" ;;
      *) die "неожиданный путь venv: $venv — удалять отказываюсь" ;;
    esac
  else
    warn "$venv отсутствует — создаю"
  fi

  command -v python3 >/dev/null 2>&1 \
    || die "python3 не найден в системе: sudo apt install -y python3 python3-venv"

  if ! (cd "$appdir" && run_as_owner python3 -m venv .venv); then
    # На Ubuntu без пакета python3-venv venv создаётся без pip → ensurepip падает.
    if command -v apt-get >/dev/null 2>&1; then
      warn "'python3 -m venv' не сработал (нет ensurepip) — ставлю python3-venv и повторяю"
      $SUDO apt-get update -qq || warn "apt-get update не удался — пробую поставить пакет как есть"
      $SUDO apt-get install -y python3-venv \
        || die "не удалось установить python3-venv — поставьте вручную: sudo apt install -y python3-venv"
      rm -rf -- "$venv"
      (cd "$appdir" && run_as_owner python3 -m venv .venv) \
        || die "не удалось создать $venv даже после установки python3-venv"
    else
      die "'python3 -m venv' не работает (нужен пакет python3-venv) — $venv не создан"
    fi
  fi

  venv_ok "$venv" || die "$venv создан, но python/pip в нём не запускаются"
  run_as_owner "$venv/bin/python" -m pip install -q --upgrade pip \
    || warn "обновить pip не вышло (офлайн?) — продолжаю на имеющемся"
  FRESH_VENV=1
  ok "$venv создан заново"
}

# install_reqs <appdir> — ставит requirements.txt; для свежесозданного venv
# ошибка фатальна (иначе сервис упадёт на импорте), для старого — предупреждение.
install_reqs() {
  local appdir="$1"
  local reqs="$appdir/requirements.txt"
  local venv="$appdir/.venv"
  [ -f "$reqs" ] || return 0
  if run_as_owner "$venv/bin/pip" install -q -r "$reqs"; then
    ok "зависимости $appdir в порядке"
  elif [ "$FRESH_VENV" -eq 1 ]; then
    die "pip install -r $reqs завершился с ошибкой (venv свежий — без зависимостей сервис не поднимется)"
  else
    warn "pip install -r $reqs завершился с ошибкой — оставлено как есть"
  fi
}

# ---------------------------------------------------------------- API
step "Backend + UI (FastAPI / Jinja2)"
cd "$ROOT/apps/api" || die "нет каталога apps/api"
ensure_venv "$ROOT/apps/api"
install_reqs "$ROOT/apps/api"
run_as_owner .venv/bin/python -m compileall -q app >/dev/null \
  || die "синтаксическая ошибка в python-коде"
ok "синтаксис в порядке"
restart_unit msb-api

# ---------------------------------------------------------- PRINT AGENT
# Агент читает формат задания из payload. Если его unit установлен и не
# выключен осознанно, обязательно чиним и перезапускаем вместе с backend —
# в том числе когда агент падает в restart-loop (activating/failed):
# раньше update.sh такой агент молча пропускал, и очередь печати висела.
if [ "$AGENT_ONLY_SKIP" -eq 1 ]; then
  ok "--api-only: print-agent не трогаю"
elif ! unit_installed msb-print-agent.service; then
  step "Print-agent"
  warn "msb-print-agent.service не установлен — пропускаю"
  warn "без агента задания печати будут копиться в очереди (см. DEPLOY.md §9)"
else
  step "Print-agent"
  state="$(unit_state msb-print-agent.service)"
  if unit_enabled msb-print-agent.service || [ "$state" = "active" ] \
     || [ "$state" = "activating" ] || [ "$state" = "failed" ]; then
    [ "$state" = "active" ] || warn "агент сейчас '$state' — чиню и перезапускаю"

    # Если unit вызывает python из другого каталога (проект переехал) —
    # починка venv здесь не поможет. Предупреждаем заранее.
    exec_path="$($SUDO systemctl show msb-print-agent.service -p ExecStart 2>/dev/null \
                 | sed -n 's/.*path=\([^ ;]*\).*/\1/p' | head -n1)"
    expected_path="$ROOT/apps/print-agent/.venv/bin/python"
    if [ -n "$exec_path" ] && [ "$exec_path" != "$expected_path" ]; then
      warn "unit вызывает '$exec_path', а update.sh собирает '$expected_path'"
      warn "переустановите unit: sudo install -m 0644 deploy/msb-print-agent.service /etc/systemd/system/ && sudo systemctl daemon-reload"
    fi

    ensure_venv "$ROOT/apps/print-agent"
    install_reqs "$ROOT/apps/print-agent"
    # Pause длиннее обычного: если ExecStart битый, агент падает мгновенно
    # и уходит в auto-restart — 2 секунды этого не ловят.
    restart_unit msb-print-agent 7
    ok "очередь печати снова обрабатывается (накопившиеся задания уйдут на принтер!)"
  else
    ok "msb-print-agent установлен, но выключен (disabled/inactive) — не трогаю"
  fi
fi

# ---------------------------------------------------------------- проверки
step "Проверка"
if command -v curl >/dev/null 2>&1; then
  api_code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "http://127.0.0.1:$API_PORT/health" 2>/dev/null); api_code=${api_code:-000}
  [ "$api_code" = "200" ] && ok "API /health → 200" || warn "API /health → $api_code (порт $API_PORT)"

  login_code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "http://127.0.0.1:$API_PORT/login" 2>/dev/null); login_code=${login_code:-000}
  if [ "$login_code" = "200" ]; then
    ok "UI /login → 200"
  else
    warn "UI /login → $login_code (порт $API_PORT)"
    have_systemd && $SUDO journalctl -u msb-api -n 30 --no-pager
  fi
else
  warn "curl не установлен — проверьте сайт вручную"
fi

if have_systemd && unit_installed msb-print-agent.service && [ "$AGENT_ONLY_SKIP" -eq 0 ]; then
  agent_state="$(unit_state msb-print-agent.service)"
  if [ "$agent_state" = "active" ]; then
    ok "print-agent: $agent_state"
  else
    warn "print-agent: ${agent_state:-unknown} — журнал: sudo journalctl -u msb-print-agent -n 100 --no-pager"
  fi
fi

echo
echo "${GRN}${BLD}Готово.${RST} Если что-то красное — покажите вывод целиком."
