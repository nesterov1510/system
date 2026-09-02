# Развёртывание MSB на `192.168.8.81`

Ниже — инструкция для **первого production-развёртывания без Docker** на
Ubuntu/Debian. Проект уже находится в каталоге
`/home/windowrepair-ae/msb`. API и Web запускаются через `systemd`, PostgreSQL —
как системная служба.

## Зафиксированная схема

| Компонент | Адрес / порт | Доступ |
|---|---|---|
| Web (Next.js) | `0.0.0.0:3030` | `http://192.168.8.81:3030` |
| API (FastAPI) | `0.0.0.0:8085` | `http://192.168.8.81:8085` |
| Swagger | `:8085/docs` | `http://192.168.8.81:8085/docs` |
| PostgreSQL | `127.0.0.1:5432` | только локально на сервере |
| Print-agent | без входящего порта | опционально, после настройки принтера |

Web-клиент обращается к относительным путям `/api`, `/media` и `/ws`. Next.js
проксирует их на `127.0.0.1:8085`, поэтому в браузере не используется
`localhost` и не возникает проблема CORS.

> Все команды далее, кроме явно отмеченных, выполняются **на сервере** под
> пользователем `windowrepair-ae`. Не запускайте одновременно эту установку и
> `docker compose`: оба варианта занимают порты `3030`, `8085` и `5432`.

---

## 1. Подключение и предварительная проверка

```bash
ssh windowrepair-ae@192.168.8.81

export MSB_ROOT=/home/windowrepair-ae/msb
cd "$MSB_ROOT"

# Должны существовать исходники и deployment-файлы.
test -f apps/api/app/main.py
test -f apps/web/package.json
test -f deploy/msb-api.service

git status --short --branch 2>/dev/null || true
```

Убедитесь, что это действительно сервер с адресом `192.168.8.81`:

```bash
hostname -I
ip -4 -brief address
```

Если IP другой, сначала закрепите `192.168.8.81` в DHCP роутера или в сетевой
конфигурации сервера. Конкретный netplan-файл зависит от имени интерфейса, поэтому
не копируйте чужую конфигурацию вслепую.

Проверьте владельца каталога и занятость портов:

```bash
id windowrepair-ae
sudo chown -R windowrepair-ae:windowrepair-ae "$MSB_ROOT"

sudo ss -ltnp | grep -E ':(3030|8085|5432)\b' || true
```

При первом развёртывании `3030` и `8085` должны быть свободны. Если там уже
работает предыдущая версия MSB, используйте раздел «Обновление», а не удаляйте
процессы вручную.

### Если файлы проекта ещё не скопированы

Этот подраздел можно пропустить, если проект уже лежит в указанном каталоге.
Например, с рабочего компьютера проект можно передать так:

```bash
rsync -av \
  --exclude '.git' --exclude '.env' --exclude '.venv' \
  --exclude 'node_modules' --exclude '.next' \
  /локальный/путь/к/msb/ \
  windowrepair-ae@192.168.8.81:/home/windowrepair-ae/msb/
```

Не копируйте локальный `.env`, виртуальные окружения, `node_modules` и `.next`.
Они создаются заново на сервере.

---

## 2. Установка системных пакетов

```bash
sudo apt update
sudo apt install -y \
  ca-certificates curl git openssl rsync iproute2 ufw \
  build-essential python3 python3-dev python3-venv python3-pip \
  fonts-dejavu-core \
  postgresql postgresql-contrib
```

Установите поддерживаемый Node.js 22 LTS (Node.js 20 уже достиг EOL):

```bash
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt install -y nodejs
```

Проверка версий и служб:

```bash
python3 --version       # Python 3.10+; 3.11/3.12 подходят
python3 -c 'import sys; assert sys.version_info >= (3, 10), "Нужен Python >= 3.10"'
node --version          # v22.x
npm --version
psql --version

sudo systemctl enable --now postgresql
sudo systemctl is-active postgresql
```

---

## 3. Создание production-окружения `.env`

Секреты ниже генерируются непосредственно на сервере. Выполните блок целиком:

```bash
export MSB_ROOT=/home/windowrepair-ae/msb
cd "$MSB_ROOT"
umask 077

DB_PASSWORD="$(openssl rand -hex 24)"
SECRET_KEY="$(openssl rand -hex 48)"
ADMIN_PASSWORD="$(openssl rand -hex 16)"

cat > .env <<EOF
# PostgreSQL
POSTGRES_USER=msb
POSTGRES_PASSWORD=${DB_PASSWORD}
POSTGRES_DB=msb
DATABASE_URL=postgresql+asyncpg://msb:${DB_PASSWORD}@127.0.0.1:5432/msb

# FastAPI
ENV=prod
SECRET_KEY=${SECRET_KEY}
PUBLIC_BASE_URL=http://192.168.8.81:3030
CORS_ORIGINS='["http://192.168.8.81:3030","http://192.168.8.81:8085"]'
STORAGE_MODE=local
UPLOAD_DIR=/home/windowrepair-ae/msb/apps/api/uploads

# Next.js: пустые значения обязательны для same-origin proxy.
NEXT_PUBLIC_API_URL=
NEXT_PUBLIC_WS_URL=

# Администратор, создаваемый только при первом запуске пустой БД.
SEED_ADMIN_EMAIL=admin@msb.local
SEED_ADMIN_PASSWORD=${ADMIN_PASSWORD}
SEED_ADMIN_PHONE=+99300000000

# Print-agent на этом же сервере. Службу пока не запускаем.
MSB_API_URL=http://127.0.0.1:8085
MSB_EMAIL=admin@msb.local
MSB_PASSWORD=${ADMIN_PASSWORD}
MSB_PRINT_CMD='lp -d EPSON_L3250 {file}'
MSB_POLL_SECONDS=3
MSB_SAVE_DIR=/home/windowrepair-ae/msb/apps/print-agent/printed
EOF

chmod 600 .env
chown windowrepair-ae:windowrepair-ae .env

printf '\nСохраните начальные данные администратора в менеджере паролей:\n'
grep '^SEED_ADMIN_EMAIL=' .env
grep '^SEED_ADMIN_PASSWORD=' .env
```

Важно:

- не добавляйте `.env` в Git и никому не отправляйте его содержимое;
- не меняйте `SECRET_KEY` при обычном обновлении — это завершит действующие
  сессии пользователей;
- сгенерированный пароль БД состоит только из hex-символов, поэтому безопасен в
  `DATABASE_URL` без URL-кодирования;
- изменение `SEED_ADMIN_PASSWORD` после создания администратора **не меняет**
  пароль в БД. После первого входа пароль меняется через интерфейс MSB.

Проверить наличие обязательных переменных, не печатая их значения:

```bash
for key in DATABASE_URL SECRET_KEY PUBLIC_BASE_URL SEED_ADMIN_PASSWORD; do
  grep -q "^${key}=.\+" .env && echo "OK: $key" || echo "ОШИБКА: $key"
done
```

---

## 4. Создание пользователя и базы PostgreSQL

Команды идемпотентны: если роль или БД уже существуют, они не удаляются.
Пароль роли приводится в соответствие с новым `.env`.

```bash
export MSB_ROOT=/home/windowrepair-ae/msb
cd "$MSB_ROOT"
DB_PASSWORD="$(sed -n 's/^POSTGRES_PASSWORD=//p' .env)"

test -n "$DB_PASSWORD" || { echo 'POSTGRES_PASSWORD не найден в .env'; exit 1; }

if [ "$(sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='msb'")" != "1" ]; then
  sudo -u postgres psql -v ON_ERROR_STOP=1 \
    -c "CREATE ROLE msb LOGIN PASSWORD '${DB_PASSWORD}'"
else
  sudo -u postgres psql -v ON_ERROR_STOP=1 \
    -c "ALTER ROLE msb WITH LOGIN PASSWORD '${DB_PASSWORD}'"
fi

if [ "$(sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='msb'")" != "1" ]; then
  sudo -u postgres createdb --owner=msb msb
fi

sudo -u postgres psql -v ON_ERROR_STOP=1 \
  -c "ALTER DATABASE msb OWNER TO msb"

PGPASSWORD="$DB_PASSWORD" psql \
  --host=127.0.0.1 --username=msb --dbname=msb \
  --command='SELECT current_database(), current_user;'
unset DB_PASSWORD

# Обычно вывод: localhost. Значение * означает прослушивание всех интерфейсов.
sudo -u postgres psql -tAc 'SHOW listen_addresses;'
sudo ss -ltnp | grep ':5432'
```

Не открывайте порт PostgreSQL `5432` в LAN: API подключается к нему локально.
На выделенном сервере MSB PostgreSQL должен слушать только `127.0.0.1`/`::1`;
если проверка показывает `0.0.0.0`, сначала проверьте, не используют ли эту БД
другие системы, затем ограничьте `listen_addresses` в конфигурации PostgreSQL.

---

## 5. Установка и запуск API (`8085`)

Создайте отдельное виртуальное окружение и установите зависимости:

```bash
export MSB_ROOT=/home/windowrepair-ae/msb
cd "$MSB_ROOT/apps/api"

python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip setuptools wheel
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m compileall -q app

mkdir -p uploads
chown -R windowrepair-ae:windowrepair-ae .venv uploads
```

Установите unit-файл и запустите API:

```bash
cd "$MSB_ROOT"
sudo install -o root -g root -m 0644 \
  deploy/msb-api.service /etc/systemd/system/msb-api.service
sudo systemctl daemon-reload
sudo systemctl enable --now msb-api
```

При первом запуске API сам создаёт таблицы, выполняет встроенные миграции и
создаёт начального администратора. Дождитесь ответа health-check:

```bash
curl --retry 15 --retry-delay 2 --retry-connrefused \
  --fail --show-error http://127.0.0.1:8085/health
echo

sudo systemctl --no-pager --full status msb-api
```

Ожидаемый ответ:

```json
{"status":"ok","app":"MSB"}
```

Если API не поднялся:

```bash
sudo journalctl -u msb-api -n 100 --no-pager
```

Сначала исправьте ошибку API и только затем запускайте Web.

---

## 6. Сборка и запуск Web (`3030`)

Переменные `NEXT_PUBLIC_API_URL` и `NEXT_PUBLIC_WS_URL` намеренно пустые. Это
заставляет браузер использовать адрес Web, а Next.js — локально проксировать
запросы на API.

```bash
export MSB_ROOT=/home/windowrepair-ae/msb
cd "$MSB_ROOT/apps/web"

npm ci --no-audit --no-fund
rm -rf .next
NEXT_PUBLIC_API_URL= NEXT_PUBLIC_WS_URL= npm run build

# Standalone-сборка Next.js не копирует эти каталоги автоматически.
rm -rf .next/standalone/.next/static .next/standalone/public
mkdir -p .next/standalone/.next
cp -a .next/static .next/standalone/.next/static
cp -a public .next/standalone/public

chown -R windowrepair-ae:windowrepair-ae .next
```

Установите unit-файл и запустите Web:

```bash
cd "$MSB_ROOT"
sudo install -o root -g root -m 0644 \
  deploy/msb-web.service /etc/systemd/system/msb-web.service
sudo systemctl daemon-reload
sudo systemctl enable --now msb-web

curl --retry 15 --retry-delay 2 --retry-connrefused \
  --fail --show-error --output /dev/null \
  http://127.0.0.1:3030/login

echo 'Web: OK'
sudo systemctl --no-pager --full status msb-web
```

Если Web не поднялся:

```bash
sudo journalctl -u msb-web -n 100 --no-pager
```

---

## 7. Доступ через firewall

Сначала узнайте фактическую LAN-подсеть:

```bash
ip route
sudo ufw status verbose
```

Если UFW уже активен и сеть — `192.168.8.0/24`, разрешите два заданных порта
только из LAN:

```bash
sudo ufw allow from 192.168.8.0/24 to any port 3030 proto tcp comment 'MSB Web'
sudo ufw allow from 192.168.8.0/24 to any port 8085 proto tcp comment 'MSB API'
sudo ufw status numbered
```

Если UFW не используется, не включайте его удалённо, пока отдельно не разрешён
SSH — иначе можно потерять доступ к серверу. Внешний интернет-доступ к `3030` и
`8085` на роутере пробрасывать не нужно.

---

## 8. Финальная проверка

### На сервере

```bash
sudo systemctl is-active postgresql msb-api msb-web
sudo systemctl is-enabled postgresql msb-api msb-web

sudo ss -ltnp | grep -E ':(3030|8085|5432)\b'

curl -fsS http://127.0.0.1:8085/health && echo
curl -fsS -o /dev/null -w 'Web HTTP %{http_code}\n' \
  http://127.0.0.1:3030/login
curl -sS -o /dev/null -w 'Web proxy API HTTP %{http_code}\n' \
  http://127.0.0.1:3030/api/auth/me
```

Для последней команды `401` — нормальный результат: он подтверждает, что Web
дошёл до API без токена.

### С другого компьютера или телефона в той же сети

Откройте:

1. `http://192.168.8.81:3030` — страница входа MSB;
2. `http://192.168.8.81:8085/health` — JSON со статусом `ok`;
3. `http://192.168.8.81:8085/docs` — Swagger.

Войдите данными из `.env`:

```bash
cd /home/windowrepair-ae/msb
grep '^SEED_ADMIN_EMAIL=' .env
grep '^SEED_ADMIN_PASSWORD=' .env
```

После входа:

1. смените пароль администратора в интерфейсе;
2. создайте отдельных сотрудников и не используйте admin для ежедневной работы;
3. проверьте создание тестового ремонта, открытие карточки и чата;
4. проверьте QR-ссылку: она должна начинаться с
   `http://192.168.8.81:3030/r/`.

> Обычный HTTP по LAN подходит для работы сайта, но браузеры обычно разрешают
> установку PWA только по HTTPS (исключение — `localhost`). Для установки PWA на
> телефоны позже потребуется HTTPS с доверенным сертификатом или локальным CA.

---

## 9. Print-agent и Epson L3250 (опционально)

Не запускайте `msb-print-agent`, пока принтер не установлен в ОС. Если агент
будет работать на другом компьютере рядом с принтером, на нём нужно указать
`MSB_API_URL=http://192.168.8.81:8085`. Ниже описан вариант на этом же Linux-
сервере.

### 9.1. Установка CUPS и принтера

```bash
sudo apt install -y cups cups-client
sudo systemctl enable --now cups

lpstat -t
lpinfo -v
```

Для сетевого принтера с поддержкой IPP Everywhere (замените IP принтера):

```bash
sudo lpadmin -p EPSON_L3250 -E \
  -v ipp://192.168.8.X/ipp/print -m everywhere
sudo lpoptions -d EPSON_L3250
lpstat -p -d
```

Если `-m everywhere` не поддерживается устройством, установите драйвер Epson и
создайте очередь через CUPS. Точное имя очереди из `lpstat -p` должно совпадать
с именем после `-d` в `MSB_PRINT_CMD`.

Тест CUPS:

```bash
printf 'MSB printer test\n' | lp -d EPSON_L3250
```

### 9.2. Учётная запись агента

Рекомендуется создать в MSB отдельного активного пользователя с ролью
`operator`, например `printer@msb.local`, и сгенерированным паролем. Затем
измените в `/home/windowrepair-ae/msb/.env` только эти строки:

```ini
MSB_EMAIL=printer@msb.local
MSB_PASSWORD=ВСТАВЬТЕ_ПАРОЛЬ_ПОЛЬЗОВАТЕЛЯ
MSB_PRINT_CMD='lp -d EPSON_L3250 {file}'
```

Пароль без пробелов и shell-символов проще всего получить командой
`openssl rand -hex 16`.

### 9.3. Установка и запуск агента

```bash
export MSB_ROOT=/home/windowrepair-ae/msb
cd "$MSB_ROOT/apps/print-agent"

python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
mkdir -p printed
chown -R windowrepair-ae:windowrepair-ae .venv printed

cd "$MSB_ROOT"
sudo install -o root -g root -m 0644 \
  deploy/msb-print-agent.service \
  /etc/systemd/system/msb-print-agent.service
sudo systemctl daemon-reload
sudo systemctl enable --now msb-print-agent

sudo systemctl --no-pager --full status msb-print-agent
sudo journalctl -u msb-print-agent -n 100 --no-pager
```

В журнале должна появиться строка `авторизация OK`. После этого создайте
тестовое задание печати из интерфейса и проверьте CUPS:

```bash
lpstat -o
find /home/windowrepair-ae/msb/apps/print-agent/printed \
  -maxdepth 1 -type f -name '*.pdf' -ls
```

---

## 10. Обновление уже установленной системы

Перед обновлением сделайте резервную копию (следующий раздел). Затем:

```bash
ssh windowrepair-ae@192.168.8.81
cd /home/windowrepair-ae/msb

# Только если сервер получает код через Git и рабочее дерево чистое:
git status --short
git pull --ff-only

# Если unit-файлы изменились, переустановить их безопасно всегда:
sudo install -o root -g root -m 0644 \
  deploy/msb-api.service /etc/systemd/system/msb-api.service
sudo install -o root -g root -m 0644 \
  deploy/msb-web.service /etc/systemd/system/msb-web.service
if systemctl list-unit-files msb-print-agent.service >/dev/null 2>&1; then
  sudo install -o root -g root -m 0644 \
    deploy/msb-print-agent.service /etc/systemd/system/msb-print-agent.service
fi
sudo systemctl daemon-reload

# Установит зависимости, проверит Python, пересоберёт Web,
# перезапустит API/Web и выполнит health-check.
sudo bash deploy/update.sh

# Агент не входит в update.sh — обновите его отдельно, если используется.
if systemctl is-enabled --quiet msb-print-agent 2>/dev/null; then
  apps/print-agent/.venv/bin/pip install -r apps/print-agent/requirements.txt
  sudo systemctl restart msb-print-agent
fi
```

После обновления:

```bash
sudo systemctl --no-pager --full status msb-api msb-web
curl -fsS http://127.0.0.1:8085/health && echo
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3030/login
```

`.env` при обновлении не заменяйте файлом `deploy/env.production`: это шаблон,
а не готовая конфигурация.

---

## 11. Резервное копирование

Минимальная резервная копия включает PostgreSQL, загруженные фотографии и
`.env` (последний храните особенно защищённо).

```bash
cd /home/windowrepair-ae/msb
umask 077
BACKUP_DIR="/home/windowrepair-ae/backups/msb-$(date +%F-%H%M%S)"
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

DB_PASSWORD="$(sed -n 's/^POSTGRES_PASSWORD=//p' .env)"
PGPASSWORD="$DB_PASSWORD" pg_dump \
  --host=127.0.0.1 --username=msb --dbname=msb \
  --format=custom --file="$BACKUP_DIR/msb.dump"
unset DB_PASSWORD

cp --preserve=mode .env "$BACKUP_DIR/msb.env"
tar -C apps/api -czf "$BACKUP_DIR/uploads.tar.gz" uploads
sha256sum "$BACKUP_DIR"/* > "$BACKUP_DIR/SHA256SUMS"
ls -lh "$BACKUP_DIR"
```

Скопируйте каталог backup на другой физический носитель или сервер. Копия на
том же диске не защищает от отказа диска.

Пример восстановления БД в заранее созданную пустую БД `msb`:

```bash
cd /home/windowrepair-ae/msb
DB_PASSWORD="$(sed -n 's/^POSTGRES_PASSWORD=//p' .env)"
PGPASSWORD="$DB_PASSWORD" pg_restore \
  --host=127.0.0.1 --username=msb --dbname=msb \
  --clean --if-exists /путь/к/msb.dump
unset DB_PASSWORD
sudo systemctl restart msb-api msb-web
```

`pg_restore --clean` изменяет текущую БД — используйте его только при
осознанном восстановлении и после дополнительной резервной копии.

---

## 12. Диагностика

### Все статусы и последние логи

```bash
sudo systemctl --no-pager --full status \
  postgresql msb-api msb-web msb-print-agent 2>/dev/null || true

sudo journalctl -u msb-api -n 100 --no-pager
sudo journalctl -u msb-web -n 100 --no-pager
sudo journalctl -u msb-print-agent -n 100 --no-pager
```

### Порт занят

```bash
sudo ss -ltnp | grep -E ':(3030|8085|5432)\b'
sudo docker ps --format 'table {{.Names}}\t{{.Ports}}' 2>/dev/null || true
```

Остановите конфликтующую старую службу или Docker Compose. Не меняйте порты в
одном месте: они зафиксированы также в unit-файлах и proxy-конфигурации.

### API не подключается к PostgreSQL

```bash
sudo systemctl status postgresql
cd /home/windowrepair-ae/msb
DB_PASSWORD="$(sed -n 's/^POSTGRES_PASSWORD=//p' .env)"
PGPASSWORD="$DB_PASSWORD" psql -h 127.0.0.1 -U msb -d msb -c 'SELECT 1;'
unset DB_PASSWORD
sudo journalctl -u msb-api -n 100 --no-pager
```

### Web открыт, но вход/API не работают

```bash
curl -i http://127.0.0.1:8085/health
curl -i http://127.0.0.1:3030/api/auth/me
```

Если API отвечает напрямую, но не через `3030`, выполните чистую пересборку:

```bash
cd /home/windowrepair-ae/msb
sudo bash deploy/update.sh --web-only
```

Убедитесь, что при сборке `NEXT_PUBLIC_API_URL` не был задан как
`http://localhost:8085` для браузерного кода. В штатной конфигурации обе
`NEXT_PUBLIC_*` переменные пустые.

### Ошибка прав на `.next`, uploads или printed

```bash
sudo chown -R windowrepair-ae:windowrepair-ae \
  /home/windowrepair-ae/msb/apps/web/.next \
  /home/windowrepair-ae/msb/apps/api/uploads \
  /home/windowrepair-ae/msb/apps/print-agent/printed 2>/dev/null || true
sudo systemctl restart msb-api msb-web
```

### Полный короткий health-check

```bash
cd /home/windowrepair-ae/msb
sudo systemctl is-active postgresql msb-api msb-web
curl -fsS http://127.0.0.1:8085/health && echo
curl -fsS -o /dev/null -w 'web=%{http_code}\n' http://127.0.0.1:3030/login
curl -fsS -o /dev/null -w 'proxy=%{http_code}\n' http://127.0.0.1:3030/api/auth/me
```

Итоговые рабочие адреса остаются:

- **MSB:** `http://192.168.8.81:3030`
- **API:** `http://192.168.8.81:8085`
- **Swagger:** `http://192.168.8.81:8085/docs`
