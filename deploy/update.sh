#!/usr/bin/env bash
# MSB — обновление сервера после изменения файлов.
#
# Делает всё в правильном порядке: сборка Next.js (standalone),
# копирование статики, перезапуск сервисов, проверка здоровья.
#
# Запуск (на сервере):
#   cd /home/windowrepair-ae/msb
#   bash deploy/update.sh            # пересобрать из того, что уже лежит на диске
#   bash deploy/update.sh --git      # сначала подтянуть ветку из GitHub
#   bash deploy/update.sh --web-only # только фронтенд
#   bash deploy/update.sh --api-only # только backend
#
# Каталог проекта берётся из переменной MSB_ROOT (по умолчанию — родительский
# каталог этого скрипта), порты — из MSB_WEB_PORT / MSB_API_PORT.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${MSB_ROOT:-$(dirname "$SCRIPT_DIR")}"
WEB_PORT="${MSB_WEB_PORT:-3030}"
API_PORT="${MSB_API_PORT:-8085}"
BRANCH="${MSB_BRANCH:-arena/01a05cc5-system}"

DO_GIT=0
DO_WEB=1
DO_API=1
for arg in "$@"; do
  case "$arg" in
    --git) DO_GIT=1 ;;
    --web-only) DO_API=0 ;;
    --api-only) DO_WEB=0 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "Неизвестный аргумент: $arg"; exit 2 ;;
  esac
done

RED=$'\e[31m'; GRN=$'\e[32m'; YLW=$'\e[33m'; BLD=$'\e[1m'; RST=$'\e[0m'
step() { echo; echo "${BLD}==> $*${RST}"; }
ok()   { echo "${GRN}  ✓ $*${RST}"; }
warn() { echo "${YLW}  ! $*${RST}"; }
die()  { echo "${RED}  ✗ $*${RST}"; exit 1; }

have_systemd() { command -v systemctl >/dev/null 2>&1; }

restart_unit() {
  local unit="$1"
  if ! have_systemd; then warn "systemctl нет — пропускаю перезапуск $unit"; return 0; fi
  sudo systemctl restart "$unit" || die "не удалось перезапустить $unit"
  sleep 2
  if sudo systemctl is-active --quiet "$unit"; then
    ok "$unit запущен"
  else
    echo "${RED}--- journalctl -u $unit -n 40 ---${RST}"
    sudo journalctl -u "$unit" -n 40 --no-pager
    die "$unit не поднялся (лог выше)"
  fi
}

echo "${BLD}MSB update${RST}  root=$ROOT  web:$WEB_PORT  api:$API_PORT"
[ -d "$ROOT/apps/web" ] || die "не найден $ROOT/apps/web — задайте MSB_ROOT=/путь/к/msb"

# ---------------------------------------------------------------- git
if [ "$DO_GIT" = 1 ]; then
  step "Обновление кода из GitHub ($BRANCH)"
  cd "$ROOT" || die "нет каталога $ROOT"
  git fetch origin "$BRANCH" || die "git fetch не прошёл"
  git checkout "$BRANCH" || die "git checkout не прошёл"
  git pull --ff-only origin "$BRANCH" || die "git pull не прошёл"
  ok "код обновлён: $(git log --oneline -1)"
fi

# ---------------------------------------------------------------- API
if [ "$DO_API" = 1 ]; then
  step "Backend (FastAPI)"
  cd "$ROOT/apps/api" || die "нет каталога apps/api"
  if [ -x .venv/bin/pip ]; then
    .venv/bin/pip install -q -r requirements.txt || warn "pip install завершился с ошибкой"
    .venv/bin/python -m compileall -q app >/dev/null || die "синтаксическая ошибка в python-коде"
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

  [ -f package-lock.json ] && { npm ci --no-audit --no-fund || die "npm ci не прошёл"; } \
                           || { npm install --no-audit --no-fund || die "npm install не прошёл"; }
  ok "зависимости установлены"

  # Чистая сборка: остатки прошлой сборки — частая причина 500 после замены файлов.
  rm -rf .next
  npm run build || die "СБОРКА УПАЛА — ошибка выше, сайт остался на старой версии"
  ok "next build выполнен"

  [ -d .next/standalone ] || die ".next/standalone не создан (проверьте output:'standalone' в next.config.mjs)"

  # Standalone-сервер не включает статику и public — их копируют вручную.
  cp -r .next/static .next/standalone/.next/static || die "не удалось скопировать .next/static"
  [ -d public ] && cp -r public .next/standalone/public
  ok "статика скопирована в standalone"

  restart_unit msb-web
fi

# ---------------------------------------------------------------- проверки
step "Проверка"
if command -v curl >/dev/null 2>&1; then
  api_code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "http://127.0.0.1:$API_PORT/health" || echo 000)
  [ "$api_code" = "200" ] && ok "API /health → 200" || warn "API /health → $api_code (порт $API_PORT)"

  web_code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "http://127.0.0.1:$WEB_PORT/login" || echo 000)
  if [ "$web_code" = "200" ]; then
    ok "Web /login → 200"
    curl -s --max-time 15 "http://127.0.0.1:$WEB_PORT/login" | grep -q "Запомнить вход" \
      && ok "чекбокс «Запомнить вход» на странице есть" \
      || warn "чекбокс не найден — возможно, отдаётся старая сборка"
  else
    warn "Web /login → $web_code (порт $WEB_PORT)"
    have_systemd && sudo journalctl -u msb-web -n 30 --no-pager
  fi
else
  warn "curl не установлен — проверьте сайт вручную"
fi

echo
echo "${GRN}${BLD}Готово.${RST} Если что-то красное — покажите вывод целиком."
