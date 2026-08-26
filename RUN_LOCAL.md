# Запуск RemontFlow локально (БЕЗ Docker)

Инструкция для локального запуска на одной машине (Linux/macOS/Windows).
Всё работает без Docker: backend (FastAPI + SQLite), frontend (Next.js),
опционально print-agent для печати бланков.

---

## 0. Что нужно установить заранее

| Компонент | Минимальная версия | Как проверить |
|---|---|---|
| Python | 3.11+ | `python3 --version` |
| Node.js | 18+ (рекоменд. 20) | `node --version` |
| npm | 9+ | `npm --version` |

Проверка:

```bash
python3 --version
node --version
npm --version
```

Если `python3` не найден — поставьте Python 3.11 или новее с [python.org](https://www.python.org/).
Если `node` не найден — поставьте LTS с [nodejs.org](https://nodejs.org/).

---

## 1. Скачайте проект

```bash
git clone https://github.com/nesterov1510/system.git
cd system
git checkout arena/01a03cd0-system
```

(Если у вас уже есть папка проекта — просто зайдите в неё.)

---

## 2. Запуск backend (FastAPI, порт 8000)

Откройте отдельный терминал и выполните:

```bash
# 2.1 Перейти в папку backend
cd system/apps/api

# 2.2 Создать виртуальное окружение (один раз)
python3 -m venv .venv

# 2.3 Активировать окружение
# Linux / macOS:
source .venv/bin/activate
# Windows (PowerShell):
# .venv\Scripts\Activate.ps1
# Windows (CMD):
# .venv\Scripts\activate.bat

# 2.4 Установить зависимости (один раз)
pip install -r requirements.txt

# 2.5 Запустить сервер
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Что произойдёт при первом запуске:
- автоматически создастся файл БД `remontflow.db` (SQLite) рядом с `main.py`;
- создадутся все таблицы;
- запишутся демо-данные (пользователи, город, точка, прайс, запчасти, несколько
  завершённых ремонтов для статистики).

**Проверка:** откройте в браузере http://localhost:8000/health — должно вернуться
`{"status":"ok",...}`. Swagger (документация API): http://localhost:8000/docs

> Примечание: по умолчанию используется **SQLite** (ничего настраивать не нужно).
> PostgreSQL подключается только через `DATABASE_URL` (см. `.env.example`).

---

## 3. Запуск frontend (Next.js, порт 3000)

Откройте **второй** терминал (backend оставьте работать):

```bash
# 3.1 Перейти в папку frontend
cd system/apps/web

# 3.2 Установить зависимости (один раз)
npm install

# 3.3 Запустить в режиме разработки
npm run dev
```

**Проверка:** откройте http://localhost:3000 — увидите экран входа RemontFlow.

Frontend проксирует запросы `/api/*` и `/media/*` на backend на `localhost:8000`
автоматически (настроено в `next.config.mjs`), поэтому отдельно настраивать адреса
не нужно.

---

## 4. Тестовые логины

При первом запуске создаются пользователи:

| Роль | Email | Пароль |
|---|---|---|
| Админ | `admin@remontflow.local` | `admin123` |
| Оператор | `operator@remontflow.local` | `operator123` |
| Мастер | `master@remontflow.local` | `master123` |
| Call-центр | `call@remontflow.local` | `call123` |
| Менеджер | `manager@remontflow.local` | `manager123` |

> Это демо-пароли только для локального запуска. В бою обязательно смените
> (админка → Пользователи, или переменные `SEED_ADMIN_*` перед первым запуском).

---

## 5. Печать бланков (Epson L3250)

Есть **два способа** подключить принтер — выбирается в админке
(`Админ → Принтер`), где указывается IP-адрес принтера и режим печати.

### Способ A (рекомендуемый): через драйвер ОС + print-agent

Надёжнее всего для струйного Epson L3250 — печать через фирменный драйвер.
Принтер подключается к компьютеру (USB или Wi-Fi), агент печатает через ОС.

Третий терминал:

```bash
cd system/apps/print-agent
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Запуск (укажите свою команду печати и логин оператора)
REMONTFLOW_API_URL=http://localhost:8000 \
REMONTFLOW_EMAIL=operator@remontflow.local \
REMONTFLOW_PASSWORD=operator123 \
REMONTFLOW_PRINT_CMD='lp -d EPSON_L3250 {file}' \
python agent.py
```

Команда печати `REMONTFLOW_PRINT_CMD` зависит от ОС:
- **Linux/macOS (CUPS):** `lp -d ИМЯ_ПРИНТЕРА {file}`
- **Windows:** `powershell -Command "Start-Process -FilePath '{file}' -Verb Print"`

Имя принтера посмотрите так:
- Linux/macOS: `lpstat -p -d`
- Windows: «Параметры → Устройства → Принтеры и сканеры»

В этом режиме IP-адрес в админке **не обязателен** (агент сам знает принтер
через ОС).

### Способ B: напрямую по IP (AirPrint/IPP)

Epson L3250 поддерживает AirPrint (IPP). Принтер должен быть в той же Wi-Fi
сети. В админке (`Админ → Принтер`) укажите:

- **Режим печати:** «Напрямую по IP (AirPrint/IPP)»
- **IP-адрес принтера** (как узнать — ниже)
- Порт: `631` (по умолчанию)

Нажмите **«Сохранить»** и **«Тестовая печать»**. print-agent (тот же самый)
отправит PDF напрямую на `http://IP:631/ipp/print`.

> ⚠️ print-agent должен работать в любом случае — именно он забирает задания
> из очереди и печатает (хоть через ОС, хоть по IP).

### Как узнать IP-адрес принтера Epson L3250

1. На панели принтера напечатайте **сетевую страницу/отчёт состояния сети**
   (обычно: зажать кнопку «Информация»/«Сеть» или через меню принтера).
2. Или в роутере (Wi-Fi) посмотрите список подключённых устройств — принтер
   Epson будет в списке со своим IP.
3. Или в приложении **Epson Smart Panel** на телефоне — там виден IP принтера.

Типичный вид адреса: `192.168.1.50` или `192.168.0.50`.

---

## 6. Запуск тестов (опционально)

```bash
cd system/apps/api
source .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest tests/ -q
```

---

## 7. Быстрая проверка, что всё работает

1. Откройте http://localhost:3000 → войдите как `admin@remontflow.local` / `admin123`.
2. Слева (или снизу на телефоне) меню: Доска / Приёмка / Call-центр / Чат / Курс / Склад.
3. Зайдите в «Доска ремонтов» — увидите канбан со статусами.
4. «Приёмка» → заполните клиента и технику → «Принять и печатать» → появится номер ремонта.
5. Откройте карточку ремонта → статус, фото, запчасти, оплата, история.

---

## 8. Частые проблемы

**Ошибка `ModuleNotFoundError` / `next: not found`**
→ не установлены зависимости. Выполните `pip install -r requirements.txt`
(backend) или `npm install` (frontend).

**Порт 8000 или 3000 уже занят**
→ либо закройте процесс, который его держит, либо запустите на другом порту:
```bash
# backend
uvicorn app.main:app --reload --port 8001
# frontend (тогда задайте адрес backend):
NEXT_PUBLIC_API_URL=http://localhost:8001 npm run dev -- -p 3001
```

**Хочу «с чистого листа» (удалить данные и демо)**
→ остановите backend, удалите файл `system/apps/api/remontflow.db`, запустите
снова — БД пересоздастся с демо-данными.

**Печать не происходит**
→ проверьте, что print-agent запущен и команда печати (`REMONTFLOW_PRINT_CMD`)
указывает на существующий принтер. Логи agent выводит в консоль.

**«мало данных» на дашборде**
→ это честное поведение статистики/AI: не хватает завершённых ремонтов.
Демо-данные добавляются при первом запуске (12 завершённых ремонтов).

---

## Порты (шпаргалка)

| Сервис | Адрес | Назначение |
|---|---|---|
| Frontend | http://localhost:3000 | веб-интерфейс |
| Backend API | http://localhost:8000 | REST API |
| Swagger | http://localhost:8000/docs | документация API |
| Health | http://localhost:8000/health | проверка живости |
