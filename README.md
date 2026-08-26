# RemontFlow

Собственная система приёмки и ремонта техники для сервисного центра.
**Без Bitrix / amoCRM / 1С как ядра** — свой backend (FastAPI), своя БД
(PostgreSQL), свой UI (Next.js PWA).

> Статус: **Итерация 0 (фундамент) + 1 (чат) + 2 (приёмка + печать)** готовы.
> Работают: PWA-форма приёмки (клиент → техника/комплект → фото/мастер/ETA →
> подтверждение), карточка ремонта с timeline/фото/комментариями, «Повторить
> печать», PDF-бланк + print-agent, публичная QR-страница, прайс и статистика
> — следующие итерации.

---

## Стек

| Слой | Технология |
|---|---|
| Frontend | Next.js (App Router) + TypeScript + Tailwind + PWA |
| Backend | FastAPI (Python 3.11) + SQLAlchemy 2.0 (async) |
| Realtime | Нативный WebSocket (FastAPI) |
| DB | PostgreSQL 16 (dev/тест — SQLite через aiosqlite) |
| Печать | PDF (ReportLab, кириллица DejaVuSans) → print-agent → принтер |
| Auth | JWT (access + refresh) + роли |

Монорепо:

```
apps/api           FastAPI backend (routers, services, models, ws)
apps/web           Next.js frontend (PWA)
apps/print-agent   агент печати на точке (A4 принтер по драйверу ОС)
packages/shared    константы статусов/ролей
docs/              kickoff-документ (ТЗ, ER, API, wireframes)
```

---

## Быстрый старт

### 1. Docker Compose (prod-подобный путь)

```bash
cp .env.example .env
# отредактируйте SECRET_KEY (длинная случайная строка)
docker compose up -d --build
```

Поднимет: PostgreSQL, API (`:8000`, Swagger на `/docs`), web (`:3000`).

### 2. Без Docker (локальная разработка)

```bash
# Backend
cd apps/api
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
# по умолчанию использует SQLite (файл remontflow.db), таблицы и сиды
# создаются автоматически при старте.
```

```bash
# Frontend
cd apps/web
npm install
npm run dev   # http://localhost:3000
```

---

## Тестовые логины (создаются при первом запуске)

| Роль | Email | Пароль |
|---|---|---|
| Админ | `admin@remontflow.local` | `admin123` |
| Оператор | `operator@remontflow.local` | `operator123` |
| Мастер | `master@remontflow.local` | `master123` |
| Call-центр | `call@remontflow.local` | `call123` |
| Менеджер | `manager@remontflow.local` | `manager123` |

> Пароли — только для локального/демо-запуска. В проде смените через админку
> `/admin/users` (или переменные `SEED_ADMIN_*` перед первым запуском).

---

## Сценарий «приёмка → печать → QR → чат» (curl)

```bash
# 1. Логин
TOKEN=$(curl -s -X POST localhost:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@remontflow.local","password":"admin123"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# 2. Город (сидируется "Москва")
CITY=$(curl -s localhost:8000/api/admin/cities -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)[0]['id'])")

# 3. Приёмка (Idempotency-Key защищает от дублей)
curl -s -X POST localhost:8000/api/repairs \
  -H "Authorization: Bearer $TOKEN" \
  -H "Idempotency-Key: $(uuidgen)" \
  -H 'Content-Type: application/json' \
  -d "{\"city_id\":\"$CITY\",\"client\":{\"full_name\":\"Иванов Иван\",\"phone\":\"+79001234567\",\"consent_pdn\":true,\"consent_storage\":true},\"device_type\":\"ТВ\",\"brand\":\"Samsung\",\"model\":\"UE55\",\"fault_client\":\"не включается\"}"

# → номер TV-MSK-2026-00001, public_token, storage_until = +3 месяца

# 4. Публичная страница по QR-токену
curl -s localhost:8000/api/public/r/{public_token}

# 5. Печать бланка (PDF A4)
curl -s -X POST localhost:8000/api/repairs/{repair_id}/print \
  -H "Authorization: Bearer $TOKEN"

# 6. Чат с упоминанием ремонта
CH=$(curl -s localhost:8000/api/chat/channels -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)[0]['id'])")
curl -s -X POST localhost:8000/api/chat/channels/$CH/messages \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"text":"Принято #TV-MSK-00001"}'
```

---

## Печать (Epson EcoTank L3250)

L3250 — **струйный A4** принтер, он **не поддерживает ESC/POS**. Бланк
печатается как PDF через драйвер ОС. Схема:

```
API рендерит PDF (кириллица) → print_jobs(queued) → print-agent забирает
→ печать через системную команду → статус done/failed + audit
```

**Запуск print-agent** на машине в той же LAN, что и принтер:

```bash
cd apps/print-agent
pip install -r requirements.txt
REMONTFLOW_API_URL=http://<api-host>:8000 \
REMONTFLOW_EMAIL=operator@remontflow.local \
REMONTFLOW_PASSWORD=operator123 \
REMONTFLOW_PRINT_CMD='lp -d EPSON_L3250 {file}' \
python agent.py
```

`REMONTFLOW_PRINT_CMD` — команда печати вашей ОС с плейсхолдером `{file}`:
- **Linux/CUPS:** `lp -d EPSON_L3250 {file}`
- **Windows:** `powershell -Command "Start-Process -FilePath '{file}' -Verb Print"`
- **macOS:** `lp -d EPSON_L3250 {file}`

Термопринтер 58/80 мм (ESC/POS, CP866) — опция на будущее, включается
feature flag `print_mode=escpos`. Текст «хранение 3 месяца», название сервиса
и другие бизнес-тексты берутся из `settings` в БД (не зашиты в код).

---

## API (кратко)

Swagger/OpenAPI: `http://localhost:8000/docs`

```
POST /api/auth/login | /refresh      GET /api/auth/me
GET  /api/chat/channels              GET/POST /api/chat/channels/:id/messages
WS   /ws?token=...                   (realtime чат + уведомления)
POST /api/repairs                    (Idempotency-Key)
GET  /api/repairs | /:id | /by-number/:number
PATCH /api/repairs/:id               POST /api/repairs/:id/events
POST /api/repairs/:id/print          GET /api/print/jobs | PATCH /api/print/jobs/:id
GET  /api/public/r/:token            (публичная QR-страница, limited DTO)
GET  /api/notifications              POST /api/notifications/:id/read
GET  /api/lookups/cities|branches|masters|complectation-items
GET/POST /api/repairs/:id/photos          (multipart фото, отдаётся через /media)
GET/POST/PATCH /api/admin/cities|branches|users
GET/PUT /api/admin/settings
```

---

## Роли и безопасность

- Роли: `admin | manager | operator | master | callcenter`.
- Каждый endpoint проверяет роль (`require_roles`); админка — только admin.
- Публичная страница отдаёт только публичные поля (без диагноза мастера,
  себестоимости и телефона клиента).
- `public_token` — 128+ бит криптослучайный, не перебираемый.
- Аудит изменений цены/статуса/печати — в `repair_events` и `audit_log`.
- Согласие на ПДн и на хранение фиксируется в `clients.consent_*_at`;
  для 152-ФЗ заложено поле `clients.deleted_at` (процедура удаления).

---

## Roadmap (итерации)

- [x] **0 — Фундамент**: монорепо, Docker, Postgres, auth (JWT+роли), модели,
      админка (юзеры/города/точки), README, .env.example
- [x] **1 — Чат**: каналы, сообщения, realtime WS, упоминание ремонта, уведомления
- [x] **2 — Приёмка + печать**: PWA-форма приёмки (клиент → техника/комплект →
      фото/мастер/ETA → подтверждение), создание Repair+Client, номер, QR-token,
      фото с камеры (multipart → /media), PDF-бланк + print-agent, «Повторить
      печать», карточка ремонта с timeline/комментариями
- [ ] **3 — Публичная QR-страница** (уже отдаётся API, нужен UI + «как обычно»)
- [ ] **4 — Доска ремонтов + роли мастера/call-центра** (канбан, очередь)
- [ ] **5 — Прайс API** + подсказки
- [ ] **6 — Дашборд статистики + AI ETA/саммари**

Подробное ТЗ, ER-модель, wireframes и риски — в `docs/remontflow-kickoff.md`.
