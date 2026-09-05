# MSB

Собственная система приёмки и ремонта техники для сервисного центра
**(полный редизайн: новый интерфейс, бренд MSB)**.
**Без Bitrix / amoCRM / 1С как ядра** — свой backend (FastAPI), своя БД
(PostgreSQL), свой UI (Next.js PWA).

> ✨ **MSB** () — современный дизайн: адаптивная доска
> ремонтов, карточки со статусами, мастер приёмки в 3 шага, касса, склад,
> статистика, чат и печать — всё в едином фирменном стиле.

> 🌍 **Регион: Туркменистан** — город Ашхабад (Asia/Ashgabat), телефоны +993,
> **валюта — туркменский манат (TMT, «ман.»)**. Цены, статистика и печать
> заточены под туркменский регион.

> Статус: **MVP (0–6) + склад + оплаты/касса + PWA-офлайн + тесты** готовы.
> Работают: PWA-форма приёмки с прайс-подсказкой, карточка ремонта
> (timeline/фото/комментарии/запчасти/**оплата**), печать с редактором шаблона бланка,
> публичная QR-страница, доска-канбан, очередь call-центра, прайс API, дашборд
> «курс ремонта» + AI-прогноз ETA, склад (запчасти + купленная техника с
> статусами разборки), **касса** (платежи/методы/выручка),
> service worker (PWA-офлайн), SMS-уведомление о готовности и ежедневные
> напоминания «заберите технику», **158 pytest-тестов**.

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
docs/              kickoff-документ (ТЗ, ER, API, wireframes)
deploy/            systemd-юниты, env.production, скрипт обновления
PROJECT_ANALYSIS.md  аудит проекта: найденные дефекты и что исправлено
```

---

## Быстрый старт

> 🚀 **Запуск без Docker** — подробная пошаговая инструкция в файле
> [`RUN_LOCAL.md`](RUN_LOCAL.md) (backend на `localhost:8085` + frontend на
> `localhost:3030`, SQLite, ничего настраивать не нужно).
>
> 🖥️ **Production на `192.168.8.81`** — полная инструкция для каталога
> `/home/windowrepair-ae/msb`, systemd, PostgreSQL и портов `3030`/`8085`:
> [`DEPLOY.md`](DEPLOY.md).

### 1. Docker Compose (prod-подобный путь)

```bash
cp .env.example .env
# отредактируйте SECRET_KEY (длинная случайная строка)
docker compose up -d --build
```

Поднимет: PostgreSQL, API (`:8085`, Swagger на `/docs`), web (`:3030`).

### 2. Без Docker (локальная разработка)

```bash
# Backend
cd apps/api
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8085
# по умолчанию использует SQLite (файл msb.db), таблицы и сиды
# создаются автоматически при старте.
```

### Тесты

```bash
cd apps/api
pip install -r requirements-dev.txt
python -m pytest tests/ -q
```

```bash
# Frontend
cd apps/web
npm install
npm run dev   # http://localhost:3030
```

---

## Доступ администратора при первом запуске

При первом запуске создаётся только один администратор. Значения задаются в `.env`:

```ini
SEED_ADMIN_EMAIL=admin@msb.local
SEED_ADMIN_PASSWORD=измените-до-продакшена
```

Никогда не публикуйте пароль в документации. После первого входа смените его в разделе «Сотрудники».

---

## Сценарий «приёмка → печать → QR → чат» (curl)

```bash
# 1. Логин
TOKEN=$(curl -s -X POST localhost:8085/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@msb.local","password":"admin123"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# 2. Город (сидируется "Ашхабад", slug=asg, Asia/Ashgabat)
CITY=$(curl -s localhost:8085/api/admin/cities -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)[0]['id'])")

# 3. Приёмка (Idempotency-Key защищает от дублей)
curl -s -X POST localhost:8085/api/repairs \
  -H "Authorization: Bearer $TOKEN" \
  -H "Idempotency-Key: $(uuidgen)" \
  -H 'Content-Type: application/json' \
  -d "{\"city_id\":\"$CITY\",\"client\":{\"full_name\":\"Иванов Иван\",\"phone\":\"+993 61 123456\",\"consent_pdn\":true,\"consent_storage\":true},\"device_type\":\"Телевизоры\",\"brand\":\"Samsung\",\"model\":\"UE55\",\"fault_client\":\"не включается\"}"

# → номер TV-ASG-2026-00001, public_token, storage_until = +3 месяца
# телефон нормализуется к 99361123456 — один и тот же человек, записанный
# как «8 61 123456», «+99361123456» или «61123456», остаётся одним клиентом

# 4. Публичная страница по QR-токену
curl -s localhost:8085/api/public/r/{public_token}

# 5. Печать бланка (PDF A4)
curl -s -X POST localhost:8085/api/repairs/{repair_id}/print \
  -H "Authorization: Bearer $TOKEN"

# 6. Чат с упоминанием ремонта
CH=$(curl -s localhost:8085/api/chat/channels -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)[0]['id'])")
curl -s -X POST localhost:8085/api/chat/channels/$CH/messages \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"text":"Принято #TV-ASG-00001"}'
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
MSB_API_URL=http://<api-host>:8085 \
MSB_EMAIL=admin@msb.local \
MSB_PASSWORD=admin123 \
MSB_PRINT_CMD='lp -d EPSON_L3250 {file}' \
python agent.py
```

`MSB_PRINT_CMD` — команда печати вашей ОС с плейсхолдером `{file}`:
- **Linux/CUPS:** `lp -d EPSON_L3250 {file}`
- **Windows:** `powershell -Command "Start-Process -FilePath '{file}' -Verb Print"`
- **macOS:** `lp -d EPSON_L3250 {file}`

Термопринтер 58/80 мм (ESC/POS, CP866) — опция на будущее, включается
feature flag `print_mode=escpos`.

### Подключение принтера Epson L3250

Настройка — в админке (`Админ → Принтер`): IP-адрес, порт, режим печати +
кнопка «Тестовая печать». Два режима:

- **`agent`** (рекомендуется) — печать через драйвер ОС (print-agent на машине с принтером).
- **`ipp`** — прямая печать по IP через AirPrint/IPP (порт 631).

Подробная инструкция и как узнать IP принтера — в [`RUN_LOCAL.md`](RUN_LOCAL.md).

### Этикетки ремонта 58×38 мм

Для USB-принтера `3B-350B`, подключённого к компьютеру `192.168.5.238`,
поддерживается отдельная PDF-этикетка: ФИО и телефон клиента, номер ремонта,
отмеченные комплектация и внешние дефекты, а также QR на авторизованную
карточку мастера. Print-agent отправляет её в удалённую
CUPS-очередь, не меняя настройку основного A4-принтера. Настройка сети, CUPS и
проверка описаны в [`LABEL_PRINTER.md`](LABEL_PRINTER.md).

## SMS-уведомления

Готовность ремонта отправляется клиенту SMS через внешний шлюз. Credentials —
только из окружения (`.env` / `deploy/env.production`):

```ini
SMS_GATEWAY_URL=https://sms.example.tm/api/send
SMS_GATEWAY_USERNAME=login
SMS_GATEWAY_PASSWORD=secret
SMS_VERIFY_SSL=true
```

Без `SMS_GATEWAY_URL` отправка отключена: API честно возвращает ошибку
(«SMS-шлюз не настроен»), а не делает вид, что сообщение ушло. Шаблоны текста и
тестовая отправка — в админке (`Админ → SMS`).

### Ежедневные напоминания «заберите технику»

Как только ремонт переведён в **«Готово к выдаче»** (кнопка «Ремонт закончен»
или смена статуса), клиенту раз в сутки уходит SMS с просьбой забрать технику —
пока ремонт не выдадут. Стандартный текст (правится в `Админ → SMS`, ключ
`pickup_reminder`):

> Уважаемый клиент, просим забрать вашу технику из нашего сервиса MERYOSAB.
> Находимся по адресу: Парахат 3/2, ж14.

Доступные плейсхолдеры: `{client_name}` `{number}` `{device}` `{days}`
`{ready_date}`. Пустой текст = текст по умолчанию.

Как это устроено:

| Что | Значение |
|---|---|
| Первое напоминание | через `REMINDER_FIRST_DELAY_HOURS` (24 ч) после готовности — в день готовности клиент уже получил SMS «ремонт готов» |
| Периодичность | `REMINDER_EVERY_HOURS` (24 ч), т.е. каждый день |
| Статусы в рассылке | «Готово к выдаче», «Не забрано» |
| Когда прекращается | «Выдано», «Архив», «Отказ» (или `REMINDER_MAX_COUNT`, если задан) |
| Тихие часы | `REMINDER_SEND_FROM_HOUR`–`REMINDER_SEND_TO_HOUR` в `REMINDER_TIMEZONE` (по умолчанию 09:00–20:00 Ашхабад) |
| Проверка очереди | фоновая задача каждые `REMINDER_CHECK_INTERVAL_MIN` минут (15) |
| Выключить совсем | `REMINDER_ENABLED=false` |

Надёжность: напоминание отправляется **ровно один раз** — перед отправкой строка
ремонта «заявляется» условным `UPDATE ... WHERE reminder_next_at = <прежнее>`,
поэтому несколько воркеров не продублируют SMS. Если шлюз не ответил, попытка
повторяется через час и не считается отправленной; при выключенном шлюзе
очередь не «сгорает» — напоминания уйдут после включения.

Каждое напоминание пишется в историю ремонта (событие `notify`) и видно:
- в карточке ремонта — чип «🔔 N · след. дата»;
- в `Админ → SMS → Очередь напоминаний` (кто ждёт, сколько отправлено, когда
  следующее) с кнопкой «▶ Прогнать сейчас» — ручной запуск рассылки.

---

## AI (Итерация 6)

AI идёт за абстракцией `app/services/ai.py`: `predict_eta()` и
`weekly_summary()`. По умолчанию (без ключа) работает **честный статистический
фолбэк** — медиана срока по истории, с явным `source: stats`. Если в `.env`
заданы `AI_API_KEY` + `AI_BASE_URL` + `AI_MODEL` (OpenAI-совместимый API),
вызывается внешняя модель. Анти-галлюцинация: при `n < 3` возвращается
`«мало данных»`, ничего не выдумывается. Каждый вызов пишется в `ai_runs`
(аудит промптов/ответов).

**Редактор шаблона бланка** — в админке (`/admin/print-templates`). Бланк
управляется шаблоном из БД (`print_templates`): название сервиса, заголовок,
подзаголовок, набор полей (клиент/телефон/техника/серийник/комплект/неисправность/
принял/мастер/хранение/срок), юртекст, футер, формат A4/A5, подписи, **раскладка
экземпляров** (по 1 на странице / **2 на одном листе с линией разреза**) и
количество копий. Кнопка «Превью» рендерит PDF. Юртекст «хранение 3 месяца»
по умолчанию берётся из `settings` (не зашит в код).

---

## API (кратко)

Swagger/OpenAPI: `http://localhost:8085/docs`

```
POST /api/auth/login | /refresh      GET /api/auth/me
GET  /api/chat/channels              GET/POST /api/chat/channels/:id/messages
WS   /ws?token=...                   (realtime чат + уведомления)
POST /api/repairs                    (Idempotency-Key)
GET  /api/repairs | /:id | /by-number/:number
PATCH /api/repairs/:id               POST /api/repairs/:id/events
PATCH /api/repairs/:id/client        (правка клиента без молчаливого переименования)
DELETE /api/repairs/:id              (admin; чистит файлы фото и пишет аудит)
POST /api/repairs/:id/finish         («Ремонт закончен» + текст SMS клиенту)
POST /api/repairs/:id/finish-sms     (отправить SMS о готовности)
GET/POST/PATCH/DELETE /api/repairs/:id/part-orders   (заказанные запчасти)
POST /api/repairs/:id/print          POST /api/repairs/:id/print-label
GET  /api/print/jobs                 PATCH /api/print/jobs/:id
GET  /api/public/r/:token            (публичная QR-страница, limited DTO + city_stats)
GET  /api/notifications              POST /api/notifications/:id/read
GET  /api/lookups/cities|branches|masters|complectation-items
GET/POST /api/repairs/:id/photos          (multipart фото, отдаётся через /media)
GET  /api/callcenter/queue?kind=agree|ready|overdue|all
GET  /api/prices?type=&brand=&model=&city=&fault  (прайс, вилка от–до + срок)
GET  /api/prices/hint                             (подсказка цены для формы)
POST/PATCH/DELETE /api/prices                     (admin/manager)
GET  /api/parts                                   (склад: каталог + остатки, ?low_stock=true)
POST/PATCH/DELETE /api/parts                      (admin/manager)
GET  /api/equipment                               (склад: купленная техника, ?q=&status=)
POST/PATCH/DELETE /api/equipment                  (admin/manager)
POST /api/equipment/:id/status                    (разобран / частично разобран)
GET/POST /api/repairs/:id/parts                   (запчасти ремонта: со склада или вручную name+price)
DELETE /api/repairs/:id/parts/:rp_id
GET/POST /api/repairs/:id/payments                (касса: платежи по ремонту)
DELETE /api/payments/:id                          (отмена платежа, admin/manager)
GET  /api/stats/overview                          (счётчики)
GET  /api/stats/tiles?type=&brand=&city=          («курс ремонта»)
POST /api/ai/predict-eta                          (прогноз ETA)
POST /api/ai/weekly-summary                       (разбор недели)
GET/POST/PATCH /api/admin/cities|branches|users
DELETE /api/admin/users/:id                        (отключение пользователя)
GET/PUT /api/admin/settings
GET  /api/admin/audit                        (журнал действий: деньги, удаления, роли)
GET/PUT /api/admin/sms | PUT /api/admin/sms/templates | POST /api/admin/sms/test
GET  /api/admin/reminders                      (очередь ежедневных напоминаний)
POST /api/admin/reminders/run                  (прогнать рассылку вручную)
GET/POST/PATCH /api/admin/print-templates        (редактор шаблона бланка)
POST /api/admin/print-templates/preview          (PDF-превью бланка)
GET/PUT /api/admin/printer                       (настройка принтера: IP/порт/режим)
POST /api/admin/printer/test                     (тестовая печать)
```

---

## Роли и безопасность

- Роли: `admin | manager | operator | master | callcenter`.
- Единая матрица прав «роль × операция» — `apps/api/app/core/permissions.py`:
  касса и финансовые поля (`price_final`, `cost_amount`, `master_payout`, `paid`)
  доступны только старшим ролям, мастер не может провести платёж или выписать
  себе выплату; назначать мастеров и закрывать ремонт могут admin/operator.
- Паспорт техники (`brand`/`model`/`serial`) принятый ремонт правится тоже только
  старшими ролями (`can_edit_device_info`): опечатку в марке исправляет оператор,
  мастер — нет. Марка не может стать пустой, каждое изменение пишется в историю
  ремонта (событие `device` со значениями «до → после») и в `audit_log`.
- Каждый endpoint проверяет роль (`require_roles`); админка — только admin.
- Публичная страница отдаёт только публичные поля (без диагноза мастера,
  себестоимости и телефона клиента).
- `public_token` — 128+ бит криптослучайный, не перебираемый.
- Аудит изменений цены/статуса/печати/удалений/ролей — в `repair_events` и
  `audit_log` (`GET /api/admin/audit`, только admin).
- Фронтенд не хранит пароль: в localStorage остаётся только email для
  автозаполнения и refresh-токен, access-токен продлевается молча по 401.
- Секреты (`SECRET_KEY`, `SMS_GATEWAY_PASSWORD`) — только из окружения,
  в коде и в репозитории их нет; `deploy/env.production` не коммитится.
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
      печать», карточка ремонта с timeline/комментариями, **редактор шаблона бланка**
- [x] **3 — Публичная QR-страница**: статус + прогресс, техника/комплект, даты,
      «хранение 3 мес», «как обычно» (обезличенная статистика), контакты, noindex + rate-limit
- [x] **4 — Доска ремонтов + роли**: канбан со статусами/фильтрами/сменой статуса,
      очередь call-центра (согласовать / готово / просрочка), мастера видят только своё
- [x] **5 — Прайс API**: справочник цен (тип/бренд/неисправность/город), вилка
      `от–до`, срок, подсказка в форме приёмки, CRUD в админке (admin/manager)
- [x] **6 — Дашборд статистики + AI**: плитки «курс ремонта» (срок/чек/p90/SLA/загрузка
      мастеров), AI-прогноз ETA с анти-галлюцинацией (`n < порога` → «мало данных»),
      weekly-summary
- [x] **7 — Склад запчастей**: каталог (название/SKU/категория/остатки/цены/поставщик),
      привязка к ремонту (списание остатков, события в timeline), low-stock в дашборде
- [x] **8 — Оплаты / касса**: платежи по ремонту (сумма/метод cash|card|transfer),
      остаток, отмена платежа (admin/manager), выручка (всего/30 дней) в дашборде
- [x] **Админка: пользователи**: CRUD сотрудников (создание/редактирование/роль/пароль/
      отключение), защита от дублей email и отключения самого себя
- [x] **Поток «мастер → оператор»**: мастер принимает заявку (автоназначение исполнителя),
      печать **2 экземпляров договора** (клиент + сервис, с подписями), оператор оформляет
      починку — **расходы + цена + отметка оплачено**, статистика с **прибылью** (выручка − расходы)
- [x] **Туркменский регион**: Ашхабад (Asia/Ashgabat), +993, валюта **TMT (ман.)** во всех ценах
- [x] **PWA-офлайн**: service worker (app-shell кеш) + manifest
- [x] **Правка техники после приёмки**: марка/модель/серийник меняются в карточке
      (✏️ у строки техники) без пересоздания ремонта — номер, этикетка и история
      остаются; след в timeline и аудите, мастерам недоступно
- [x] **Компактная таблица «Все ремонты»**: короткие заголовки колонок
      (`📅 Дата`, `📺 Техника`, `🧾 Принял`, `🔧 Причина`, `💵 Сумма`, `🔩 Запчасти`,
      `👤 Клиент`, `👷 Мастера`, `💰 Выплата`, `🏁 Итог`) + кнопка-пояснение `?`
      у каждой колонки (`components/ColumnHint.tsx`); в «Итог» добавлен бейдж оплаты
- [x] **Тесты**: 158 pytest-тестов (auth/чат/ремонты/прайс/склад/оплаты/админ/
      статистика/AI/печать/SMS/напоминания/правка техники + 39 регрессионных на
      исправленные дефекты — `apps/api/tests/test_fixed_defects.py`)
- [x] **Аудит и исправления**: матрица прав, аудит действий, нормализация
      телефонов, идемпотентная приёмка с retry нумерации, валидация статусов,
      оверлейное боковое меню и облегчённая карточка ремонта

Подробное ТЗ, ER-модель, wireframes и риски — в `docs/msb-kickoff.md`.
