# 🚀 Развёртывание MSB — пошаговая инструкция

Система состоит из трёх компонентов:

| Компонент | Технология | Порт | Папка на сервере |
|-----------|-----------|------|-------------------|
| **API** (бэкенд) | FastAPI (Python 3.11) | **8085** | `/home/windowrepair-ae/msb/apps/api` |
| **Web** (фронтенд) | Next.js (Node.js) | **3030** | `/home/windowrepair-ae/msb/apps/web` |
| **print-agent** | Python-скрипт | — | `/home/windowrepair-ae/msb/apps/print-agent` |
| **PostgreSQL** | 16+ | 5432 | системный пакет |

---

## 1. 📦 Установка PostgreSQL

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y postgresql postgresql-contrib

# Запуск
sudo systemctl enable --now postgresql

# Создание БД и пользователя
sudo -u postgres psql -c "CREATE USER msb WITH PASSWORD 'ЗАМЕНИТЕ_НА_СЛОЖНЫЙ_ПАРОЛЬ';"
sudo -u postgres psql -c "CREATE DATABASE msb OWNER msb;"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE msb TO msb;"

# Проверка подключения
psql -U msb -d msb -h localhost -W
```

---

## 2. 📂 Копирование проекта на сервер

```bash
# На сервере:
mkdir -p /home/windowrepair-ae/msb

# Скопируйте файлы (с вашего ПК на сервер):
# Вариант A — через scp (с вашего ПК):
scp -r /путь/к/проекту/* windowrepair-ae@192.168.8.81:/home/windowrepair-ae/msb/

# Вариант B — через git:
cd /home/windowrepair-ae/msb
git init
git remote add origin <URL-вашего-репозитория>
git pull origin main
```

---

## 3. 🐍 Настройка API (FastAPI)

### 3.1. Установка зависимостей

```bash
cd /home/windowrepair-ae/msb/apps/api

# Создание виртуального окружения
python3 -m venv .venv
source .venv/bin/activate

# Установка пакетов
pip install --upgrade pip
pip install -r requirements.txt
```

### 3.2. Настройка .env

Создайте файл `/home/windowrepair-ae/msb/.env`:

```ini
# --- БД ---
POSTGRES_USER=msb
POSTGRES_PASSWORD=ЗАМЕНИТЕ_НА_СЛОЖНЫЙ_ПАРОЛЬ
POSTGRES_DB=msb

DATABASE_URL=postgresql+asyncpg://msb:ЗАМЕНИТЕ_НА_СЛОЖНЫЙ_ПАРОЛЬ@localhost:5432/msb

# --- API ---
SECRET_KEY=ЗАМЕНИТЕ_НА_ДЛИННУЮ_СЛУЧАЙНУЮ_СТРОКУ
# Сгенерировать: python3 -c "import secrets; print(secrets.token_urlsafe(48))"

PUBLIC_BASE_URL=http://192.168.8.81:3030

# --- Web (оставить пустыми — прокси через Next.js) ---
NEXT_PUBLIC_API_URL=
NEXT_PUBLIC_WS_URL=

# --- Seed ---
SEED_ADMIN_EMAIL=admin@msb.local
SEED_ADMIN_PASSWORD=admin123

# --- print-agent ---
MSB_API_URL=http://192.168.8.81:8085
MSB_EMAIL=operator@msb.local
MSB_PASSWORD=operator123
MSB_PRINT_CMD=lp -d EPSON_L3250 {file}
```

### 3.3. Запуск для проверки

```bash
cd /home/windowrepair-ae/msb/apps/api
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8085 --log-level info
```

Откройте в браузере: http://192.168.8.81:8085/docs — должен загрузиться Swagger.

Остановите (Ctrl+C), переходим к systemd.

### 3.4. Systemd-сервис

```bash
sudo cp /home/windowrepair-ae/msb/deploy/msb-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now msb-api

# Проверка
sudo systemctl status msb-api
journalctl -u msb-api -f
```

---

## 4. ⚛️ Настройка Web (Next.js)

### 4.1. Установка Node.js

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

# Проверка
node --version  # >= 20
npm --version
```

### 4.2. Сборка фронтенда

```bash
cd /home/windowrepair-ae/msb/apps/web

# Установка зависимостей
npm ci

# Сборка (production)
npm run build

# Копирование статики в standalone
cp -r .next/static .next/standalone/.next/static
```

### 4.3. Тестовый запуск

```bash
cd /home/windowrepair-ae/msb/apps/web
PORT=3030 HOST=0.0.0.0 node .next/standalone/server.js
```

Откройте http://192.168.8.81:3030 — должен загрузиться интерфейс MSB.

Остановите, переходим к systemd.

### 4.4. Systemd-сервис

```bash
sudo cp /home/windowrepair-ae/msb/deploy/msb-web.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now msb-web

# Проверка
sudo systemctl status msb-web
journalctl -u msb-web -f
```

---

## 5. 🖨️ Настройка print-agent

### 5.1. Установка зависимостей

```bash
cd /home/windowrepair-ae/msb/apps/print-agent

python3 -m venv .venv
source .venv/bin/activate
pip install requests
```

### 5.2. Тестовый запуск

```bash
MSB_API_URL=http://192.168.8.81:8085 \
MSB_EMAIL=operator@msb.local \
MSB_PASSWORD=operator123 \
MSB_PRINT_CMD="lp -d EPSON_L3250 {file}" \
python agent.py
```

Должно появиться: `[print-agent] авторизация OK`

### 5.3. Systemd-сервис

```bash
sudo cp /home/windowrepair-ae/msb/deploy/msb-print-agent.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable -now msb-print-agent

# Проверка
sudo systemctl status msb-print-agent
journalctl -u msb-print-agent -f
```

---

## 6. 🔥 Настройка Nginx (опционально)

Если нужен единый порт 80 и терминиция TLS:

```nginx
# /etc/nginx/sites-availble/msb
server {
    listen 80;
    server_name 192.168.8.81;

    # Фронтенд
    location / {
        proxy_pass http://127.0.0.1:3030;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
    }

    # WebSockets (для чата)
    location /ws {
        proxy_pass http://127.0.0.1:8085;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/msb /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

---

## 7. ✅ Проверка работоспособности

```bash
# Статус сервисов
sudo systemctl status msb-api msb-web msb-print-agent

# Health-check API
curl http://192.168.8.81:8085/health
# → {"status": "ok", "app": "MSB"}

# Открыть в браузере
# http://192.168.8.81:3030
```

---

## 8. 🐞 Типичные проблемы

### print-agent не видит принтер

```bash
# Список принтеров CUPS
lpstat -p

# Если принтер есть — укажите точное имя в MSB_PRINT_CMD
MSB_PRINT_CMD="lp -d <точное_имя> {file}"

# Если принтер по сети — проверть соединение
nc -zv 192.168.5.206 631   # IPP-port
nc -zv 192.168.5.206 9100  # Raw socket
```

### Web не грузится (белый экран)

```bash
# Проверть журнал
journalctl -u msb-web -n 50

# Пересобрать
cd /home/windowrepair-ae/msb/apps/web
npm run build
cp -r .next/static .next/standalone/.next/static
sudo systemctl restart msb-web
```

### Ошибка подключения к БД

```bash
# Проверть что PostgreSQL запущен и слушает
sudo systemctl status postgresql
ss -tlnp | grep 5432

# Проверть строку подключения в .env
grep DATABASE_URL /home/windowrepair-ae/msb/.env
```

---

## 9. 🔄 Обновление системы

```bash
cd /home/windowrepair-ae/msb

# Если через git:
git pull origin main

# API:
cd apps/api
source .venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart msb-api

# Web:
cd apps/web
npm ci
npm run build
cp -r .next/static .next/standalone/.next/static
sudo systemctl restart msb-web

# print-agent:
cd apps/print-agent
source .venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart msb-print-agent
```