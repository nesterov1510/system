#!/usr/bin/env bash
# MSB — пересборка и перезапуск системы после изменения файлов.
#
# Скрипт ничего не скачивает: он собирает то, что уже лежит на диске,
# и перезапускает сервисы от имени администратора (root).
#
# Запуск (на сервере):
#   cd /home/windowrepair-ae/msb
#   sudo bash deploy/update.sh              # обновить web + api
#   sudo bash deploy/update.sh --web-only   # только фронтенд
#   sudo bash deploy/update.sh --api-only   # только backend
#
# Можно запускать и без sudo — права администратора будут запрошены сами
# (для systemctl). Каталог проекта берётся из MSB_ROOT (по умолчанию —
# родительский каталог этого скрипта), порты — из MSB_WEB_PORT / MSB_API_PORT.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${MSB_ROOT:-$(dirname "$SCRIPT_DIR")}"
WEB_PORT="${MSB_WEB_PORT:-3030}"
API_PORT="${MSB_API_PORT:-8085}"

DO_WEB=1
DO_API=1
for arg in "$@"; do
  case "$arg" in
    --web-only) DO_API=0 ;;
    --api-only) DO_WEB=0 ;;
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

echo "${BLD}MSB update${RST}  root=$ROOT  web:$WEB_PORT  api:$API_PORT"
[ -d "$ROOT/apps/web" ] || die "не найден $ROOT/apps/web — задайте MSB_ROOT=/путь/к/msb"

# Владелец каталога проекта: под root собираем от его имени, чтобы файлы
# сборки не стали root-овыми и следующий запуск без sudo не сломался.
OWNER="$(stat -c '%U' "$ROOT/apps/web")"
OWNER_GRP="$(stat -c '%G' "$ROOT/apps/web")"
run_as_owner() {
  if [ "$(id -u)" -eq 0 ] && [ "$OWNER" != "root" ] && command -v runuser >/dev/null 2>&1; then
    runuser -u "$OWNER" -- "$@"
  else
    "$@"
  fi
}

# ---------------------------------------------------------------- API
if [ "$DO_API" = 1 ]; then
  step "Backend (FastAPI)"
  cd "$ROOT/apps/api" || die "нет каталога apps/api"
  if [ -x .venv/bin/pip ]; then
    run_as_owner .venv/bin/pip install -q -r requirements.txt || warn "pip install завершился с ошибкой"
    run_as_owner .venv/bin/python -m compileall -q app >/dev/null || die "синтаксическая ошибка в python-коде"
    ok "зависимости и синтаксис в порядке"
  else
    warn ".venv не найден — пропускаю установку зависимостей"
  fi
  restart_unit msb-api
fi

# ---------------------------------------------------------------- WEB
if [ "$DO_WEB" = 1 ]; then
  step "Frontend (Next.js standalone)"
  cd "$ROOT/apps/web" || die "нет каталога apps/web"

  if [ -f package-lock.json ]; then
    run_as_owner npm ci --no-audit --no-fund || die "npm ci не прошёл"
  else
    run_as_owner npm install --no-audit --no-fund || die "npm install не прошёл"
  fi
  ok "зависимости установлены"

  # Чистая сборка: остатки прошлой сборки — частая причина 500 после замены файлов.
  rm -rf .next
  # Для native/systemd deployment браузер всегда использует same-origin.
  # Пустые NEXT_PUBLIC_* не дают случайно зашить localhost/IP в JS-бандл.
  run_as_owner env NEXT_PUBLIC_API_URL= NEXT_PUBLIC_WS_URL= npm run build \
    || die "СБОРКА УПАЛА — Web не перезапущен; исправьте ошибку и повторите обновление"
  ok "next build выполнен"

  [ -d .next/standalone ] || die ".next/standalone не создан (проверьте output:'standalone' в next.config.mjs)"

  # Standalone-сервер не включает статику и public — их копируют вручную.
  cp -r .next/static .next/standalone/.next/static || die "не удалось скопировать .next/static"
  [ -d public ] && cp -r public .next/standalone/public
  ok "статика скопирована в standalone"

  # Вернуть владельца, если что-то создалось от root.
  if [ "$(id -u)" -eq 0 ] && [ "$OWNER" != "root" ]; then
    chown -R "$OWNER:$OWNER_GRP" .next 2>/dev/null
  fi

  restart_unit msb-web
fi

# ---------------------------------------------------------------- проверки
step "Проверка"
if command -v curl >/dev/null 2>&1; then
  api_code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "http://127.0.0.1:$API_PORT/health" 2>/dev/null); api_code=${api_code:-000}
  [ "$api_code" = "200" ] && ok "API /health → 200" || warn "API /health → $api_code (порт $API_PORT)"

  web_code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "http://127.0.0.1:$WEB_PORT/login" 2>/dev/null); web_code=${web_code:-000}
  if [ "$web_code" = "200" ]; then
    ok "Web /login → 200"
    curl -s --max-time 15 "http://127.0.0.1:$WEB_PORT/login" | grep -q "Запомнить вход" \
      && ok "чекбокс «Запомнить вход» на странице есть" \
      || warn "чекбокс не найден — возможно, отдаётся старая сборка"
  else
    warn "Web /login → $web_code (порт $WEB_PORT)"
    have_systemd && $SUDO journalctl -u msb-web -n 30 --no-pager
  fi
else
  warn "curl не установлен — проверьте сайт вручную"
fi

echo
echo "${GRN}${BLD}Готово.${RST} Если что-то красное — покажите вывод целиком."
