#!/usr/bin/env bash
# =============================================================================
# MSB — единый скрипт управления развёртыванием на сервере.
#
#   Сервер:   192.168.8.81, порт 8085
#   Проект:   /home/windowrepair-ae/msb   (владелец windowrepair-ae)
#   Службы:   msb-api.service (обязательно), msb-print-agent.service (опция)
#   БД:       PostgreSQL на 127.0.0.1:5432, роль/база msb   (или --sqlite)
#
# ИСПОЛЬЗОВАНИЕ:  sudo bash deploy/msb.sh <команда> [параметры]
#
#   install [--repo URL] [--branch BR] [--from-dir DIR] [--sqlite] [--with-agent]
#           Полное развёртывание с нуля (идемпотентно — можно повторять):
#           пакеты → пользователь → код в MSB_ROOT → .env с секретами →
#           PostgreSQL роль+база → venv + зависимости → unit-файлы systemd →
#           enable + start → firewall → health-check.
#             --repo URL     взять код через git clone (ветка --branch, по умолч. main)
#             --from-dir DIR скопировать код из каталога (rsync, без .git/.env/.venv)
#             (без опций)    код берётся из каталога, где лежит этот скрипт,
#                            либо уже должен лежать в MSB_ROOT
#             --sqlite       без PostgreSQL: база в файле apps/api/msb.db
#             --with-agent   сразу включить msb-print-agent (нужен CUPS/принтер)
#
#   uninstall [--purge] [--purge-user] [--no-backup] [--yes]
#           Удалить службы из systemd (stop + disable + rm unit + daemon-reload).
#           Код, .env и база остаются.
#             --purge        дополнительно удалить каталог проекта, базу и роль
#                            PostgreSQL (перед этим делается резервная копия
#                            в /home/<user>/backups, если не --no-backup)
#             --purge-user   удалить и системного пользователя windowrepair-ae
#             --yes          не спрашивать подтверждение (для автоматизации)
#
#   start | stop | restart | status | logs [-f] [N]
#           Управление службами. status — состояние, порт, /health, версия.
#
#   update [--branch BR]
#           Обновить код (git pull, если каталог — git-репозиторий) и
#           пересобрать/перезапустить через deploy/update.sh.
#
#   backup [DIR]
#           pg_dump (или копия msb.db) + uploads + .env → DIR
#           (по умолчанию /home/<user>/backups/msb-<дата>).
#
#   enable-agent | disable-agent
#           Включить/выключить print-agent, не трогая API.
#
#   env     Показать .env без секретов (пароли замаскированы).
#
# ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ (переопределяют значения по умолчанию):
#   MSB_ROOT=/home/windowrepair-ae/msb   MSB_USER=windowrepair-ae
#   MSB_HOST=192.168.8.81                MSB_API_PORT=8085
#   MSB_LAN=192.168.8.0/24               MSB_DB_NAME=msb  MSB_DB_USER=msb
#
# ПРИМЕРЫ:
#   # 1) на сервере уже распакован проект в /home/windowrepair-ae/msb:
#   cd /home/windowrepair-ae/msb && sudo bash deploy/msb.sh install
#   # 2) с нуля, код из GitHub:
#   curl -fsSL https://raw.githubusercontent.com/nesterov1510/system/main/deploy/msb.sh -o msb.sh
#   sudo bash msb.sh install --repo https://github.com/nesterov1510/system.git --branch main
#   # 3) снести всё:
#   sudo bash deploy/msb.sh uninstall --purge
# =============================================================================
set -uo pipefail

# ------------------------------------------------------------------ параметры
MSB_ROOT="${MSB_ROOT:-/home/windowrepair-ae/msb}"
MSB_USER="${MSB_USER:-windowrepair-ae}"
MSB_HOST="${MSB_HOST:-192.168.8.81}"
API_PORT="${MSB_API_PORT:-8085}"
MSB_LAN="${MSB_LAN:-192.168.8.0/24}"
DB_NAME="${MSB_DB_NAME:-msb}"
DB_USER="${MSB_DB_USER:-msb}"
DB_HOST="127.0.0.1"
DB_PORT="5432"

API_UNIT="msb-api"
AGENT_UNIT="msb-print-agent"
UNIT_DIR="/etc/systemd/system"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RED=$'\e[31m'; GRN=$'\e[32m'; YLW=$'\e[33m'; BLD=$'\e[1m'; RST=$'\e[0m'
step() { echo; echo "${BLD}==> $*${RST}"; }
ok()   { echo "${GRN}  ✓ $*${RST}"; }
warn() { echo "${YLW}  ! $*${RST}"; }
err()  { echo "${RED}  ✗ $*${RST}"; }
die()  { err "$*"; exit 1; }

usage() { sed -n '2,66p' "$0" | sed 's/^# \{0,1\}//'; }

# ------------------------------------------------------------------ root
need_root() {
  if [ "$(id -u)" -ne 0 ]; then
    command -v sudo >/dev/null 2>&1 || die "нужны права администратора: sudo bash $0 $*"
    exec sudo -E MSB_ROOT="$MSB_ROOT" MSB_USER="$MSB_USER" MSB_HOST="$MSB_HOST" \
      MSB_API_PORT="$API_PORT" MSB_LAN="$MSB_LAN" MSB_DB_NAME="$DB_NAME" MSB_DB_USER="$DB_USER" \
      bash "$0" "$@"
  fi
}

have() { command -v "$1" >/dev/null 2>&1; }
have_systemd() { have systemctl && [ -d /run/systemd/system ]; }
unit_installed() { [ -f "$UNIT_DIR/$1.service" ]; }
unit_active() { systemctl is-active --quiet "$1" 2>/dev/null; }
unit_enabled() { systemctl is-enabled --quiet "$1" 2>/dev/null; }

run_as_user() {
  # Команды над файлами проекта — от имени владельца, чтобы не плодить root-файлы.
  if [ "$(id -u)" -eq 0 ] && id "$MSB_USER" >/dev/null 2>&1; then
    runuser -u "$MSB_USER" -- "$@"
  else
    "$@"
  fi
}

# copy_tree <src> <dst> — код проекта без .git/.env/.venv/uploads (rsync или tar).
copy_tree() {
  local src="$1" dst="$2"
  local ex=(.git .env .venv __pycache__ uploads printed '*.db' node_modules .pytest_cache)
  mkdir -p "$dst"
  if have rsync; then
    local args=(); local e; for e in "${ex[@]}"; do args+=(--exclude "$e"); done
    rsync -a "${args[@]}" "$src/" "$dst/"
  else
    local args=(); local e; for e in "${ex[@]}"; do args+=(--exclude "$e"); done
    tar -C "$src" "${args[@]}" -cf - . | tar -C "$dst" -xf -
  fi
}

env_get() { sed -n "s/^$1=//p" "$MSB_ROOT/.env" 2>/dev/null | head -n1 | sed "s/^['\"]//;s/['\"]$//"; }
is_sqlite() { case "$(env_get DATABASE_URL)" in sqlite*) return 0;; *) return 1;; esac; }
sqlite_path() { env_get DATABASE_URL | sed -E 's#^[a-z+]+:///##'; }

# =============================================================================
#                                  INSTALL
# =============================================================================
cmd_install() {
  local repo="" branch="main" from_dir="" use_sqlite=0 with_agent=0
  while [ $# -gt 0 ]; do
    case "$1" in
      --repo) repo="$2"; shift 2 ;;
      --branch) branch="$2"; shift 2 ;;
      --from-dir) from_dir="$2"; shift 2 ;;
      --sqlite) use_sqlite=1; shift ;;
      --with-agent) with_agent=1; shift ;;
      -h|--help) usage; exit 0 ;;
      *) die "install: неизвестный параметр $1" ;;
    esac
  done

  echo "${BLD}MSB install${RST}  root=$MSB_ROOT  user=$MSB_USER  http://$MSB_HOST:$API_PORT"
  have_systemd || die "systemd не найден — этот скрипт рассчитан на Ubuntu/Debian с systemd"

  # ---------------------------------------------------------- 1. пакеты
  step "1/9 Системные пакеты"
  if have apt-get; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq || warn "apt-get update не удался (нет интернета?) — пробую поставить то, что есть в кеше"
    apt-get install -y -qq ca-certificates curl git openssl rsync iproute2 \
      build-essential python3 python3-dev python3-venv python3-pip \
      fonts-dejavu-core >/dev/null || die "не удалось установить базовые пакеты"
    [ "$use_sqlite" -eq 1 ] || apt-get install -y -qq postgresql-client >/dev/null || warn "postgresql-client не установлен"
    ok "пакеты установлены"
  else
    warn "apt-get не найден — убедитесь вручную, что есть python3 (>=3.10), python3-venv, git, curl, openssl, rsync"
  fi
  python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
    || die "нужен Python >= 3.10 (сейчас $(python3 --version 2>&1))"
  ok "python: $(python3 --version 2>&1)"

  # ---------------------------------------------------------- 2. пользователь
  step "2/9 Пользователь $MSB_USER"
  if id "$MSB_USER" >/dev/null 2>&1; then
    ok "пользователь существует"
  else
    useradd --create-home --shell /bin/bash "$MSB_USER" || die "не удалось создать пользователя $MSB_USER"
    ok "пользователь создан (без пароля; вход по ssh настройте отдельно, если нужен)"
  fi
  # Служба сама печатает в CUPS через агент — доступ к lp полезен.
  getent group lp >/dev/null 2>&1 && usermod -aG lp "$MSB_USER" 2>/dev/null || true

  # ---------------------------------------------------------- 3. код
  step "3/9 Код проекта → $MSB_ROOT"
  local src_root
  src_root="$(dirname "$SCRIPT_DIR")"
  if [ -n "$repo" ]; then
    if [ -d "$MSB_ROOT/.git" ]; then
      ok "уже git-репозиторий — обновляю ветку $branch"
      run_as_user git -C "$MSB_ROOT" fetch --all --prune || die "git fetch не удался"
      run_as_user git -C "$MSB_ROOT" checkout -q "$branch" || die "нет ветки $branch"
      run_as_user git -C "$MSB_ROOT" pull --ff-only || die "git pull не удался (локальные правки?)"
    elif [ -d "$MSB_ROOT/apps/api" ]; then
      die "$MSB_ROOT уже содержит проект, но не git — уберите --repo или очистите каталог (uninstall --purge)"
    else
      mkdir -p "$(dirname "$MSB_ROOT")"
      git clone --branch "$branch" "$repo" "$MSB_ROOT" || die "git clone $repo не удался"
      ok "клонирован $repo ($branch)"
    fi
  elif [ -n "$from_dir" ]; then
    [ -f "$from_dir/apps/api/app/main.py" ] || die "в $from_dir нет проекта MSB (apps/api/app/main.py)"
    copy_tree "$from_dir" "$MSB_ROOT" || die "копирование из $from_dir не удалось"
    ok "скопировано из $from_dir"
  elif [ -f "$MSB_ROOT/apps/api/app/main.py" ]; then
    ok "проект уже на месте"
  elif [ -f "$src_root/apps/api/app/main.py" ] && [ "$src_root" != "$MSB_ROOT" ]; then
    copy_tree "$src_root" "$MSB_ROOT" || die "копирование из $src_root не удалось"
    ok "скопировано из $src_root (каталог, где лежит скрипт)"
  else
    die "код не найден: положите проект в $MSB_ROOT или укажите --repo URL / --from-dir DIR"
  fi
  [ -f "$MSB_ROOT/apps/api/app/main.py" ] || die "в $MSB_ROOT нет apps/api/app/main.py"
  chown -R "$MSB_USER:$MSB_USER" "$MSB_ROOT"
  ok "владелец: $MSB_USER"

  # ---------------------------------------------------------- 4. .env
  step "4/9 Конфигурация .env"
  local envf="$MSB_ROOT/.env"
  if [ -f "$envf" ]; then
    ok ".env уже есть — не трогаю (секреты сохранены)"
    if grep -q 'CHANGE_ME' "$envf"; then
      warn "в .env остались значения CHANGE_ME — замените их: nano $envf"
    fi
  else
    local db_pass secret admin_pass upload_dir
    db_pass="$(openssl rand -hex 24)"
    secret="$(openssl rand -hex 48)"
    admin_pass="$(openssl rand -base64 18 | tr -d '/+=' | cut -c1-16)"
    upload_dir="$MSB_ROOT/apps/api/uploads"
    local db_url
    if [ "$use_sqlite" -eq 1 ]; then
      db_url="sqlite+aiosqlite:///$MSB_ROOT/apps/api/msb.db"
    else
      db_url="postgresql+asyncpg://$DB_USER:$db_pass@$DB_HOST:$DB_PORT/$DB_NAME"
    fi
    umask 077
    cat > "$envf" <<EOF
# MSB production — создано deploy/msb.sh $(date '+%F %T')
# Полное описание параметров: deploy/env.production, DEPLOY.md

# --- База данных ---
POSTGRES_USER=$DB_USER
POSTGRES_PASSWORD=$db_pass
POSTGRES_DB=$DB_NAME
DATABASE_URL=$db_url

# --- FastAPI ---
ENV=prod
SECRET_KEY=$secret
PUBLIC_BASE_URL=http://$MSB_HOST:$API_PORT
CORS_ORIGINS='["http://$MSB_HOST:$API_PORT"]'
STORAGE_MODE=local
UPLOAD_DIR=$upload_dir

# --- Первый администратор (используется только при пустой базе) ---
SEED_ADMIN_EMAIL=admin@msb.local
SEED_ADMIN_PASSWORD=$admin_pass
SEED_ADMIN_PHONE=+99300000000

# --- SMS-шлюз (можно настроить позже в «Настройки → SMS-шлюз») ---
SMS_GATEWAY_URL=
SMS_GATEWAY_USERNAME=
SMS_GATEWAY_PASSWORD=
SMS_VERIFY_SSL=true

# --- Напоминания «заберите технику» ---
REMINDER_ENABLED=true
REMINDER_CHECK_INTERVAL_MIN=15
REMINDER_EVERY_HOURS=24
REMINDER_FIRST_DELAY_HOURS=24
REMINDER_SEND_FROM_HOUR=9
REMINDER_SEND_TO_HOUR=20
REMINDER_TIMEZONE=Asia/Ashgabat
REMINDER_MAX_COUNT=0

# --- Print-agent на этом же сервере (служба включается отдельно) ---
MSB_API_URL=http://127.0.0.1:$API_PORT
MSB_EMAIL=admin@msb.local
MSB_PASSWORD=$admin_pass
MSB_POLL_SECONDS=3
MSB_SAVE_DIR=$MSB_ROOT/apps/print-agent/printed
EOF
    umask 022
    chown "$MSB_USER:$MSB_USER" "$envf"; chmod 600 "$envf"
    ok ".env создан, секреты сгенерированы"
    echo
    echo "  ${BLD}Первый вход в систему:${RST}  http://$MSB_HOST:$API_PORT/login"
    echo "  ${BLD}  логин:  ${RST}admin@msb.local"
    echo "  ${BLD}  пароль: ${RST}$admin_pass"
    echo "  (сохранён в $envf → SEED_ADMIN_PASSWORD; смените после входа)"
    echo
  fi

  # ---------------------------------------------------------- 5. PostgreSQL
  step "5/9 База данных"
  if is_sqlite; then
    ok "SQLite: $(sqlite_path)"
  else
    setup_postgres
  fi

  # ---------------------------------------------------------- 6. venv
  step "6/9 Python-окружение и зависимости"
  make_venv "$MSB_ROOT/apps/api"
  run_as_user "$MSB_ROOT/apps/api/.venv/bin/python" -m compileall -q "$MSB_ROOT/apps/api/app" >/dev/null \
    || die "синтаксическая ошибка в коде API"
  run_as_user mkdir -p "$MSB_ROOT/apps/api/uploads"
  ok "API готов"
  if [ -f "$MSB_ROOT/apps/print-agent/requirements.txt" ]; then
    make_venv "$MSB_ROOT/apps/print-agent"
    run_as_user mkdir -p "$MSB_ROOT/apps/print-agent/printed"
    ok "print-agent готов (служба $( [ "$with_agent" -eq 1 ] && echo включается || echo 'НЕ включается — см. enable-agent'))"
  fi

  # ---------------------------------------------------------- 7. systemd
  step "7/9 Службы systemd"
  install_units
  systemctl daemon-reload
  systemctl enable "$API_UNIT" >/dev/null 2>&1
  systemctl restart "$API_UNIT" || true
  ok "$API_UNIT: enabled + started"
  if [ "$with_agent" -eq 1 ]; then
    systemctl enable "$AGENT_UNIT" >/dev/null 2>&1
    systemctl restart "$AGENT_UNIT" || true
    ok "$AGENT_UNIT: enabled + started"
  else
    systemctl disable "$AGENT_UNIT" >/dev/null 2>&1 || true
  fi

  # ---------------------------------------------------------- 8. firewall
  step "8/9 Firewall"
  if have ufw && ufw status 2>/dev/null | grep -q '^Status: active'; then
    ufw allow from "$MSB_LAN" to any port "$API_PORT" proto tcp comment 'MSB UI/API' >/dev/null \
      && ok "ufw: разрешён $API_PORT/tcp из $MSB_LAN" || warn "ufw: не удалось добавить правило"
  else
    ok "ufw не активен — правила не нужны (не включайте ufw удалённо без правила для ssh!)"
  fi

  # ---------------------------------------------------------- 9. проверка
  step "9/9 Проверка"
  wait_health 60 || {
    journalctl -u "$API_UNIT" -n 60 --no-pager
    die "API не поднялся — лог выше. После исправления: sudo bash $0 restart"
  }
  cmd_status
  echo
  echo "${GRN}${BLD}Установка завершена.${RST}  Откройте http://$MSB_HOST:$API_PORT/login"
  echo "Обновление в будущем:  sudo bash $MSB_ROOT/deploy/msb.sh update"
}

setup_postgres() {
  if ! (have pg_isready && pg_isready -h "$DB_HOST" -p "$DB_PORT" -q 2>/dev/null); then
    if [ -x /usr/lib/postgresql ] || dpkg -l 2>/dev/null | grep -q '^ii  postgresql '; then
      systemctl enable --now postgresql >/dev/null 2>&1 || true
    fi
    if ! pg_isready -h "$DB_HOST" -p "$DB_PORT" -q 2>/dev/null; then
      warn "PostgreSQL на $DB_HOST:$DB_PORT не отвечает — устанавливаю"
      apt-get install -y -qq postgresql postgresql-contrib >/dev/null || die "не удалось установить postgresql"
      systemctl enable --now postgresql || die "postgresql не запустился"
      sleep 2
    fi
  fi
  pg_isready -h "$DB_HOST" -p "$DB_PORT" -q || die "PostgreSQL не отвечает на $DB_HOST:$DB_PORT"
  ok "PostgreSQL работает"

  local db_pass; db_pass="$(env_get POSTGRES_PASSWORD)"
  [ -n "$db_pass" ] || die "POSTGRES_PASSWORD не найден в $MSB_ROOT/.env"
  id postgres >/dev/null 2>&1 || die "нет системного пользователя postgres — создайте роль/базу $DB_NAME вручную (DEPLOY.md §4)"

  if [ "$(runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'")" != "1" ]; then
    runuser -u postgres -- psql -v ON_ERROR_STOP=1 -q -c "CREATE ROLE $DB_USER LOGIN PASSWORD '$db_pass'" \
      || die "CREATE ROLE $DB_USER не удался"
    ok "роль $DB_USER создана"
  else
    runuser -u postgres -- psql -v ON_ERROR_STOP=1 -q -c "ALTER ROLE $DB_USER WITH LOGIN PASSWORD '$db_pass'" \
      || die "ALTER ROLE $DB_USER не удался"
    ok "роль $DB_USER: пароль синхронизирован с .env"
  fi
  if [ "$(runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'")" != "1" ]; then
    runuser -u postgres -- createdb --owner="$DB_USER" "$DB_NAME" || die "createdb $DB_NAME не удался"
    ok "база $DB_NAME создана"
  else
    runuser -u postgres -- psql -v ON_ERROR_STOP=1 -q -c "ALTER DATABASE $DB_NAME OWNER TO $DB_USER" >/dev/null 2>&1 || true
    ok "база $DB_NAME существует (данные сохранены)"
  fi
  PGPASSWORD="$db_pass" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -tAc 'SELECT 1' >/dev/null 2>&1 \
    && ok "подключение $DB_USER@$DB_NAME по паролю — OK" \
    || die "не удаётся подключиться к $DB_NAME под $DB_USER (проверьте pg_hba.conf: md5/scram для 127.0.0.1)"
}

make_venv() {
  local appdir="$1" venv="$1/.venv"
  if ! ( [ -x "$venv/bin/python" ] && run_as_user "$venv/bin/python" -m pip --version >/dev/null 2>&1 ); then
    rm -rf "$venv"
    (cd "$appdir" && run_as_user python3 -m venv .venv) || die "python3 -m venv в $appdir не удался (sudo apt install python3-venv)"
    run_as_user "$venv/bin/python" -m pip install -q --upgrade pip setuptools wheel || warn "обновить pip не удалось (офлайн?)"
  fi
  run_as_user "$venv/bin/pip" install -q -r "$appdir/requirements.txt" \
    || die "pip install -r $appdir/requirements.txt не удался"
  ok "venv $appdir/.venv"
}

# Unit-файлы генерируются под фактические MSB_ROOT / MSB_USER / порт —
# шаблоны в deploy/*.service жёстко зашиты под стандартные значения.
install_units() {
  cat > "$UNIT_DIR/$API_UNIT.service" <<EOF
# Создано deploy/msb.sh — MSB FastAPI backend + UI ($MSB_ROOT, порт $API_PORT)
[Unit]
Description=MSB API + UI (FastAPI / Jinja2)
After=network-online.target postgresql.service
Wants=network-online.target

[Service]
Type=simple
User=$MSB_USER
Group=$MSB_USER
WorkingDirectory=$MSB_ROOT/apps/api
EnvironmentFile=$MSB_ROOT/.env
Environment=PYTHONUNBUFFERED=1
# Один worker намеренно: при старте приложение мигрирует схему и выполняет seed.
ExecStart=$MSB_ROOT/apps/api/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port $API_PORT --workers 1 --log-level info
Restart=on-failure
RestartSec=5
TimeoutStartSec=120
TimeoutStopSec=30
UMask=0027
NoNewPrivileges=true
ProtectHome=false
ProtectSystem=full
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF
  cat > "$UNIT_DIR/$AGENT_UNIT.service" <<EOF
# Создано deploy/msb.sh — MSB print-agent (очередь печати, CUPS / raw TSPL)
[Unit]
Description=MSB Print Agent (printer queue poller)
After=network-online.target $API_UNIT.service cups.service
Wants=network-online.target $API_UNIT.service

[Service]
Type=simple
User=$MSB_USER
Group=$MSB_USER
WorkingDirectory=$MSB_ROOT/apps/print-agent
EnvironmentFile=$MSB_ROOT/.env
Environment=PYTHONUNBUFFERED=1
ExecStart=$MSB_ROOT/apps/print-agent/.venv/bin/python agent.py
Restart=on-failure
RestartSec=5
TimeoutStartSec=60
TimeoutStopSec=30
UMask=0027
NoNewPrivileges=true
ProtectHome=false
ProtectSystem=full
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF
  chmod 644 "$UNIT_DIR/$API_UNIT.service" "$UNIT_DIR/$AGENT_UNIT.service"
  ok "unit-файлы записаны в $UNIT_DIR"
}

wait_health() {
  local tries="${1:-30}" i code
  for i in $(seq 1 "$tries"); do
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "http://127.0.0.1:$API_PORT/health" 2>/dev/null || true)"
    [ "$code" = "200" ] && { ok "API /health → 200 (через ${i} с)"; return 0; }
    unit_active "$API_UNIT" || { [ "$i" -gt 3 ] && break; }
    sleep 1
  done
  err "API не отвечает на http://127.0.0.1:$API_PORT/health"
  return 1
}

# =============================================================================
#                                 UNINSTALL
# =============================================================================
cmd_uninstall() {
  local purge=0 purge_user=0 do_backup=1 yes=0
  while [ $# -gt 0 ]; do
    case "$1" in
      --purge) purge=1; shift ;;
      --purge-user) purge=1; purge_user=1; shift ;;
      --no-backup) do_backup=0; shift ;;
      --yes|-y) yes=1; shift ;;
      -h|--help) usage; exit 0 ;;
      *) die "uninstall: неизвестный параметр $1" ;;
    esac
  done

  echo "${BLD}MSB uninstall${RST}  root=$MSB_ROOT"
  echo "  Будет сделано:"
  echo "   • остановлены и удалены службы $API_UNIT, $AGENT_UNIT"
  if [ "$purge" -eq 1 ]; then
    [ "$do_backup" -eq 1 ] && echo "   • резервная копия базы, фото и .env → /home/$MSB_USER/backups"
    echo "   • ${RED}удалён каталог $MSB_ROOT (код, .env, фото)${RST}"
    is_sqlite 2>/dev/null || echo "   • ${RED}удалены база PostgreSQL '$DB_NAME' и роль '$DB_USER'${RST}"
    [ "$purge_user" -eq 1 ] && echo "   • ${RED}удалён системный пользователь $MSB_USER с домашним каталогом${RST}"
    echo "   • удалено правило ufw для порта $API_PORT"
  else
    echo "   • код, .env, база и фото ОСТАЮТСЯ (для полного удаления: --purge)"
  fi
  if [ "$yes" -ne 1 ]; then
    local word="УДАЛИТЬ"
    [ "$purge" -eq 1 ] || word="да"
    printf '\nВведите «%s» для подтверждения: ' "$word"
    read -r answer
    [ "$answer" = "$word" ] || die "отменено"
  fi

  if [ "$purge" -eq 1 ] && [ "$do_backup" -eq 1 ] && [ -f "$MSB_ROOT/.env" ]; then
    step "Резервная копия перед удалением"
    cmd_backup "" || warn "резервная копия не удалась — продолжаю (вы просили --purge)"
  fi

  step "Службы systemd"
  local u
  for u in "$AGENT_UNIT" "$API_UNIT"; do
    if unit_installed "$u"; then
      systemctl stop "$u" 2>/dev/null || true
      systemctl disable "$u" 2>/dev/null || true
      rm -f "$UNIT_DIR/$u.service"
      ok "$u остановлен и удалён"
    else
      ok "$u не был установлен"
    fi
  done
  systemctl daemon-reload
  systemctl reset-failed 2>/dev/null || true
  # Добить процесс, если он был запущен вручную вне systemd.
  if have ss && ss -ltnp 2>/dev/null | grep -q ":$API_PORT "; then
    warn "порт $API_PORT всё ещё занят — процесс запущен вне systemd? $(ss -ltnp 2>/dev/null | grep ":$API_PORT " | grep -o 'users:.*' | head -n1)"
  fi

  if [ "$purge" -eq 1 ]; then
    step "Firewall"
    if have ufw; then
      # удаляем все правила с нашим портом (ufw не умеет удалять по комментарию)
      while ufw status numbered 2>/dev/null | grep -q " $API_PORT/tcp"; do
        local n; n="$(ufw status numbered | grep " $API_PORT/tcp" | head -n1 | sed 's/^\[ *\([0-9]*\)\].*/\1/')"
        [ -n "$n" ] || break
        ufw --force delete "$n" >/dev/null 2>&1 || break
      done
      ok "правила ufw для $API_PORT удалены"
    fi

    step "База данных"
    if [ -f "$MSB_ROOT/.env" ] && is_sqlite; then
      ok "SQLite — удалится вместе с каталогом"
    elif id postgres >/dev/null 2>&1 && pg_isready -h "$DB_HOST" -p "$DB_PORT" -q 2>/dev/null; then
      runuser -u postgres -- psql -q -c "DROP DATABASE IF EXISTS $DB_NAME WITH (FORCE)" 2>/dev/null \
        || runuser -u postgres -- psql -q -c "DROP DATABASE IF EXISTS $DB_NAME" || warn "не удалось удалить базу $DB_NAME"
      runuser -u postgres -- psql -q -c "DROP ROLE IF EXISTS $DB_USER" || warn "не удалось удалить роль $DB_USER"
      ok "база $DB_NAME и роль $DB_USER удалены (сам PostgreSQL не трогаем — им могут пользоваться другие)"
    else
      warn "PostgreSQL недоступен — базу $DB_NAME удалите вручную, если она есть"
    fi

    step "Файлы"
    case "$MSB_ROOT" in
      /|/home|/root|/usr|/etc|/var|"") die "отказываюсь удалять $MSB_ROOT" ;;
    esac
    if [ -d "$MSB_ROOT" ]; then
      rm -rf -- "$MSB_ROOT"
      ok "каталог $MSB_ROOT удалён"
    else
      ok "каталога $MSB_ROOT нет"
    fi
    if [ "$purge_user" -eq 1 ] && id "$MSB_USER" >/dev/null 2>&1; then
      pkill -u "$MSB_USER" 2>/dev/null || true
      userdel -r "$MSB_USER" 2>/dev/null && ok "пользователь $MSB_USER удалён" \
        || warn "не удалось удалить пользователя $MSB_USER (открыта сессия?): sudo userdel -r $MSB_USER"
    fi
  fi

  echo
  echo "${GRN}${BLD}Готово.${RST}"
  [ "$purge" -eq 1 ] || echo "Повторный запуск служб: sudo bash $MSB_ROOT/deploy/msb.sh install"
}

# =============================================================================
#                         START / STOP / RESTART / STATUS / LOGS
# =============================================================================
units_present() {
  unit_installed "$API_UNIT" || die "$API_UNIT.service не установлен — выполните: sudo bash $0 install"
}

cmd_start() {
  units_present
  systemctl start "$API_UNIT" && ok "$API_UNIT запущен" || die "$API_UNIT не запустился"
  unit_enabled "$AGENT_UNIT" && { systemctl start "$AGENT_UNIT" && ok "$AGENT_UNIT запущен"; }
  wait_health 40 || journalctl -u "$API_UNIT" -n 40 --no-pager
}

cmd_stop() {
  units_present
  systemctl stop "$AGENT_UNIT" 2>/dev/null || true
  systemctl stop "$API_UNIT" && ok "$API_UNIT остановлен"
}

cmd_restart() {
  units_present
  systemctl restart "$API_UNIT" && ok "$API_UNIT перезапущен" || die "$API_UNIT не перезапустился"
  unit_enabled "$AGENT_UNIT" && { systemctl restart "$AGENT_UNIT" && ok "$AGENT_UNIT перезапущен"; }
  wait_health 40 || journalctl -u "$API_UNIT" -n 40 --no-pager
}

cmd_status() {
  echo "${BLD}MSB status${RST}  $MSB_ROOT  →  http://$MSB_HOST:$API_PORT"
  local u st en
  for u in "$API_UNIT" "$AGENT_UNIT"; do
    if unit_installed "$u"; then
      st="$(systemctl is-active "$u" 2>/dev/null || true)"
      en="$(systemctl is-enabled "$u" 2>/dev/null || true)"
      case "${st:-inactive}" in
        active) ok "$u: active (${en:-?})" ;;
        inactive) [ "$u" = "$AGENT_UNIT" ] && ok "$u: выключен (${en:-disabled})" || warn "$u: остановлен (${en:-?})" ;;
        *) err "$u: $st (${en:-?}) — журнал: sudo bash $0 logs$( [ "$u" = "$AGENT_UNIT" ] && echo ' agent' )" ;;
      esac
    else
      [ "$u" = "$API_UNIT" ] && err "$u: не установлен" || ok "$u: не установлен"
    fi
  done
  if have ss; then
    if ss -ltn 2>/dev/null | grep -q ":$API_PORT "; then ok "порт $API_PORT слушается"; else warn "порт $API_PORT не слушается"; fi
  fi
  local code; code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://127.0.0.1:$API_PORT/health" 2>/dev/null || true)"
  [ "$code" = "200" ] && ok "/health → 200" || warn "/health → ${code:-нет ответа}"
  if [ -f "$MSB_ROOT/.env" ]; then
    is_sqlite && ok "БД: SQLite $(sqlite_path)" || ok "БД: PostgreSQL $DB_USER@$DB_HOST:$DB_PORT/$DB_NAME"
  fi
  if [ -d "$MSB_ROOT/.git" ]; then
    ok "код: $(git -C "$MSB_ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null) @ $(git -C "$MSB_ROOT" rev-parse --short HEAD 2>/dev/null) ($(git -C "$MSB_ROOT" log -1 --format=%cd --date=short 2>/dev/null))"
  fi
  if [ -d "$MSB_ROOT/apps/api/uploads" ]; then
    ok "фото: $(du -sh "$MSB_ROOT/apps/api/uploads" 2>/dev/null | cut -f1) в uploads/"
  fi
}

cmd_logs() {
  local follow=0 n=100 unit="$API_UNIT"
  while [ $# -gt 0 ]; do
    case "$1" in
      -f) follow=1; shift ;;
      agent) unit="$AGENT_UNIT"; shift ;;
      ''|*[!0-9]*) shift ;;
      *) n="$1"; shift ;;
    esac
  done
  if [ "$follow" -eq 1 ]; then journalctl -u "$unit" -n "$n" -f; else journalctl -u "$unit" -n "$n" --no-pager; fi
}

# =============================================================================
#                                UPDATE / BACKUP
# =============================================================================
cmd_update() {
  local branch=""
  while [ $# -gt 0 ]; do
    case "$1" in --branch) branch="$2"; shift 2 ;; *) die "update: неизвестный параметр $1" ;; esac
  done
  [ -d "$MSB_ROOT/apps/api" ] || die "проект не найден в $MSB_ROOT"
  step "Код"
  if [ -d "$MSB_ROOT/.git" ]; then
    if [ -n "$(run_as_user git -C "$MSB_ROOT" status --porcelain 2>/dev/null)" ]; then
      warn "в $MSB_ROOT есть локальные изменения — git pull может не пройти"
      run_as_user git -C "$MSB_ROOT" status --short | head -n 20
    fi
    run_as_user git -C "$MSB_ROOT" fetch --all --prune || die "git fetch не удался"
    [ -n "$branch" ] && { run_as_user git -C "$MSB_ROOT" checkout -q "$branch" || die "нет ветки $branch"; }
    run_as_user git -C "$MSB_ROOT" pull --ff-only || die "git pull --ff-only не удался — разберитесь с локальными правками"
    ok "код: $(git -C "$MSB_ROOT" rev-parse --abbrev-ref HEAD) @ $(git -C "$MSB_ROOT" rev-parse --short HEAD)"
  else
    ok "не git-репозиторий — считаю, что файлы уже обновлены (rsync)"
  fi
  chown -R "$MSB_USER:$MSB_USER" "$MSB_ROOT"
  # Unit-файлы могли измениться (порт/пути) — перезаписываем безопасно.
  install_units; systemctl daemon-reload
  if [ -f "$MSB_ROOT/deploy/update.sh" ]; then
    MSB_ROOT="$MSB_ROOT" MSB_API_PORT="$API_PORT" bash "$MSB_ROOT/deploy/update.sh"
  else
    make_venv "$MSB_ROOT/apps/api"; cmd_restart
  fi
}

cmd_backup() {
  local dir="${1:-}"
  [ -f "$MSB_ROOT/.env" ] || die "нет $MSB_ROOT/.env — нечего копировать"
  [ -n "$dir" ] || dir="/home/$MSB_USER/backups/msb-$(date +%F-%H%M%S)"
  mkdir -p "$dir"; chmod 700 "$dir"
  if is_sqlite; then
    local dbf; dbf="$(sqlite_path)"
    [ -f "$dbf" ] && { cp "$dbf" "$dir/msb.db"; ok "SQLite → msb.db"; } || warn "файл базы $dbf не найден"
  else
    local db_pass; db_pass="$(env_get POSTGRES_PASSWORD)"
    if have pg_dump; then
      PGPASSWORD="$db_pass" pg_dump -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
        --format=custom --file="$dir/msb.dump" && ok "pg_dump → msb.dump" || warn "pg_dump не удался"
    else
      warn "pg_dump не найден (apt install postgresql-client)"
    fi
  fi
  cp --preserve=mode "$MSB_ROOT/.env" "$dir/msb.env" && ok ".env → msb.env"
  if [ -d "$MSB_ROOT/apps/api/uploads" ]; then
    tar -C "$MSB_ROOT/apps/api" -czf "$dir/uploads.tar.gz" uploads && ok "фото → uploads.tar.gz"
  fi
  (cd "$dir" && sha256sum ./* > SHA256SUMS 2>/dev/null) || true
  chown -R "$MSB_USER:$MSB_USER" "$(dirname "$dir")" 2>/dev/null || true
  ok "резервная копия: $dir ($(du -sh "$dir" | cut -f1))"
  echo "  Скопируйте её на другой носитель. Восстановление БД: DEPLOY.md §11."
}

cmd_enable_agent() {
  unit_installed "$AGENT_UNIT" || { install_units; systemctl daemon-reload; }
  [ -x "$MSB_ROOT/apps/print-agent/.venv/bin/python" ] || make_venv "$MSB_ROOT/apps/print-agent"
  systemctl enable --now "$AGENT_UNIT" && ok "$AGENT_UNIT включён" || die "$AGENT_UNIT не запустился"
  sleep 3; journalctl -u "$AGENT_UNIT" -n 15 --no-pager
  echo "  В .env должны быть MSB_EMAIL / MSB_PASSWORD активного пользователя MSB (DEPLOY.md §9)."
}

cmd_disable_agent() {
  systemctl disable --now "$AGENT_UNIT" 2>/dev/null; ok "$AGENT_UNIT выключен"
}

cmd_env() {
  [ -f "$MSB_ROOT/.env" ] || die "нет $MSB_ROOT/.env"
  sed -E 's/^((POSTGRES_PASSWORD|SECRET_KEY|SEED_ADMIN_PASSWORD|MSB_PASSWORD|SMS_GATEWAY_PASSWORD)=).+/\1********/; s#(://[^:]+:)[^@]+@#\1********@#' "$MSB_ROOT/.env"
}

# =============================================================================
#                                    MAIN
# =============================================================================
cmd="${1:-}"; shift || true
case "$cmd" in
  install)        need_root install "$@";        cmd_install "$@" ;;
  uninstall|remove) need_root uninstall "$@";    cmd_uninstall "$@" ;;
  start)          need_root start "$@";          cmd_start ;;
  stop)           need_root stop "$@";           cmd_stop ;;
  restart)        need_root restart "$@";        cmd_restart ;;
  status)         cmd_status ;;
  logs)           need_root logs "$@";           cmd_logs "$@" ;;
  update)         need_root update "$@";         cmd_update "$@" ;;
  backup)         need_root backup "$@";         cmd_backup "${1:-}" ;;
  enable-agent)   need_root enable-agent;        cmd_enable_agent ;;
  disable-agent)  need_root disable-agent;       cmd_disable_agent ;;
  env)            cmd_env ;;
  -h|--help|help|"") usage ;;
  *) die "неизвестная команда: $cmd (см. --help)" ;;
esac
