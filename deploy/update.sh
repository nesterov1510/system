#!/usr/bin/env bash
# MSB — пересборка и перезапуск системы после изменения файлов.
#
# Скрипт ничего не скачивает: он собирает то, что уже лежит на диске,
# и перезапускает сервисы от имени администратора (root).
#
# Запуск (на сервере):
#   cd /home/windowrepair-ae/msb
#   sudo bash deploy/update.sh              # api + активный print-agent
#   sudo bash deploy/update.sh --api-only   # то же (фронтенд отдельного нет)
#
# Можно запускать и без sudo — права администратора будут запрошены сами
# (для systemctl). Каталог проекта берётся из MSB_ROOT (по умолчанию —
# родительский каталог этого скрипта), порт API — из MSB_API_PORT.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${MSB_ROOT:-$(dirname "$SCRIPT_DIR")}"
API_PORT="${MSB_API_PORT:-8085}"

for arg in "$@"; do
  case "$arg" in
    --web-only)
      echo "Отдельного фронтенда больше нет (Jinja2 UI отдаёт API на :$API_PORT)."
      echo "Используйте: sudo bash deploy/update.sh"
      exit 0
      ;;
    --api-only) ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "Неизвестный аргумент: $arg"; exit 2 ;;
  esac
done

RED=$'\e[31m'; GRN=$'\e[32m'; YLW=$'\e[33m'; BLD=$'\e[1m'; RST=$'\e[0m'
step() { echo; echo "${BLD}==> $*${RST}"; }
ok()   { echo "${GRN}  ✓ $*${RST}"; }
warn() { echo "${YLW}  ! $*${RST}"; }
die()  { echo "${RED}  ✗ $*${RST}"; exit 1; }

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

restart_unit() {
  local unit="$1"
  if ! have_systemd; then warn "systemctl нет — пропускаю перезапуск $unit"; return 0; fi
  $SUDO systemctl restart "$unit" || die "не удалось перезапустить $unit"
  sleep 2
  if $SUDO systemctl is-active --quiet "$unit"; then
    ok "$unit перезапущен (root)"
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
OWNER_GRP="$(stat -c '%G' "$ROOT/apps/api")"
run_as_owner() {
  if [ "$(id -u)" -eq 0 ] && [ "$OWNER" != "root" ] && command -v runuser >/dev/null 2>&1; then
    runuser -u "$OWNER" -- "$@"
  else
    "$@"
  fi
}

# ---------------------------------------------------------------- API
step "Backend + UI (FastAPI / Jinja2)"
cd "$ROOT/apps/api" || die "нет каталога apps/api"
if [ -x .venv/bin/pip ]; then
  run_as_owner .venv/bin/pip install -q -r requirements.txt || warn "pip install завершился с ошибкой"
  run_as_owner .venv/bin/python -m compileall -q app >/dev/null || die "синтаксическая ошибка в python-коде"
  ok "зависимости и синтаксис в порядке"
else
  warn ".venv не найден — пропускаю установку зависимостей"
fi
restart_unit msb-api

# ---------------------------------------------------------- PRINT AGENT
# Агент читает формат задания из payload. Если он уже запущен, обязательно
# перезапускаем его вместе с backend, чтобы новые типы заданий не ушли не туда.
if have_systemd \
   && $SUDO systemctl is-active --quiet msb-print-agent.service; then
  step "Print-agent"
  if [ -x "$ROOT/apps/print-agent/.venv/bin/pip" ]; then
    run_as_owner "$ROOT/apps/print-agent/.venv/bin/pip" install -q \
      -r "$ROOT/apps/print-agent/requirements.txt" \
      || warn "не удалось обновить зависимости print-agent"
  fi
  restart_unit msb-print-agent
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

echo
echo "${GRN}${BLD}Готово.${RST} Если что-то красное — покажите вывод целиком."
