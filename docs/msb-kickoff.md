# MSB — Kickoff / ТЗ-ответ на суперпромпт

> Система приёмки и ремонта техники для сервисного центра. **Без Bitrix / amoCRM / 1С как ядра.**
> Свой backend, своя БД, свой UI. Язык продукта — русский.
> Статус: документ-старт (пункты 1–10 OUTPUT). Код не пишем до «ОК» заказчика.

> **UPD (после «ОК» заказчика):** принтер — **Epson EcoTank L3250**, это
> **струйный A4** (не термопринтер, **ESC/POS не поддерживается**). Печать
> бланка реализована как **PDF (ReportLab, кириллица DejaVuSans) → print-agent
> → системный драйвер ОС**. Ниже в разделах 4/7/9 оставлены правки под A4;
> ESC/POS оставлен как опция на будущее (feature flag `print_mode`).

---

## 0. Зафиксированные решения (ответы на блокирующие вопросы)

| Вопрос | Ответ | Следствие для архитектуры |
|---|---|---|
| Backend-стек | **FastAPI (Python)** | Pydantic-схемы = source of truth, OpenAPI → генерация TS-типов для фронта |
| Масштаб на старте | **1 город, 1 точка** | Модель остаётся мульти-город/точка, но UI-обвязка и печать заточены под 1 точку |
| Принтер | **Epson EcoTank L3250 (LAN/Wi-Fi)** | струйный A4, **без ESC/POS** → печать PDF через драйвер ОС (print-agent); кириллица DejaVuSans |
| Офлайн-режим приёмки в v1 | **Нет, только online** | Outbox-очередь на клиенте → итерация позже |
| Прайс | **С нуля** | CRUD + ручной ввод в MVP; импорт CSV/Excel — следующим шагом, не блокер |
| Уведомления клиенту | **Бумага + QR достаточно** | SMS/WhatsApp — опция позже, за интерфейсом (feature flag) |

---

## 1. Блокирующие вопросы (короткий список)

**Закрыто (см. таблицу выше):** стек, масштаб, принтер, офлайн, прайс, уведомления.

**Открытые (жду от заказчика, с дефолтами — не блокируют старт):**

1. **Модель Epson** — TM-T88 / TM-T20 / TM-m30? (влияет на код code page и ширину ленты 58 vs 80 мм). Дефолт: 80 мм, CP866, сырой TCP 9100.
2. **Термолента + A4-акт или только термо?** Дефолт: термочек (клиенту + корешок) + PDF-fallback, A4-акт позже.
3. **Юр. текст «хранение 3 месяца»** — есть готовый? Дефолт: настраиваемый текст в `settings`, стартовый шаблон подготовим сами (не хардкод).
4. **Название / лого / домен** — см. пункт 2 (5 названий), домен предложен.
5. **Число сотрудников на старте** — операторы/мастера/call. Дефолт: 2–4 оператора, 2–3 мастера, 1–2 call, 1 менеджер. На модель данных и роли не влияет (роли уже заданы).

---

## 2. Названия продукта + slug

| # | Название | Slug | Смысл |
|---|---|---|---|
| 1 | **MSB** | `msb` | «Поток ремонтов» — рабочее имя, отражает конвейер «приёмка → ремонт → выдача» |
| 2 | **MasterDesk** | `masterdesk` | «Стойка приёма/мастера» — акцент на оператора за стойкой |
| 3 | **Priёmka** (Приёмка) | `priemka` | Короткое, нативное, ядро продукта — приёмка за 30–60 сек |
| 4 | **ServisBox** | `servisbox` | «Коробка» сервиса: всё в одном месте |
| 5 | **RemontPro** | `remontpro` | Простое, понятное, легко запоминается |

Рекомендация: **MSB** (уже укоренилось в ТЗ). Домен: `msb.ru` (или `remont.{город}.ru`). Slug используется в URL монолита и в номерах ремонта (`TV-MSK-…` → заменить город на slug точки).

---

## 3. Product brief (1 страница)

**Что это.** Собственная web/PWA-система сервисного центра по ремонту ТВ и бытовой техники: оператор с телефона за 30–60 секунд принимает технику, сразу печатает бланк на Epson-чеке, в системе открывается ремонт, call-центр ведёт клиента, на бланке QR с условиями хранения 3 месяца, внутри — прайс, сроки по городу и AI-статистика «как курс доллара», снимающая сомнения в ремонте.

**Почему своя, а не Bitrix.** Узкий быстрый UX под стойку приёмки (не «комбайн»), полный контроль данных/печати/прайса/AI, дешевле развивать под один бизнес-процесс. Интеграции (1С, касса) — только опционально и позже.

**Пользователи.** Оператор/приёмщик, мастер, call-центр, клиент (QR-страница), менеджер/владелец, админ.

**Ядро (MVP MUST).** Приёмка → печать → карточка ремонта → чат; затем прайс, статусы, call-центр, статистика, AI.

**Главный поток.** Приёмка (мобильная форма → номер `TV-{city}-{YYYY}-{NNNNN}` → запись в БД → timeline → job печати → QR-бланк) → жизненный цикл статусов (Принято → Диагностика → Согласование → Ожидание запчастей → В ремонте → Готово к выдаче → Выдано / Не забрано / Архив / Отказ) → call-центр (очереди «согласовать/готово/просрочка») → прайс API → статистика+AI.

**Не-цели MVP.** Склад, оплаты, клиентский кабинет, телефония, боты, выездные мастера, 1С. Всё это — позже.

**Метрики успеха (DoD-ориентиры).** Приёмка < 1 мин с телефона; бланк уходит на принтер (или PDF-fallback); ремонт виден со статусом «Принято»; QR открывает публичную страницу; прайс отдаёт вилку; дашборд показывает средний срок по городу+типу; AI честно говорит «мало данных» при n < порога.

**Стек.** Next.js (App Router, TS, Tailwind, shadcn/ui, PWA) + FastAPI (Python) + PostgreSQL + Redis (+RQ для очереди печати/фонов) + MinIO/S3 (фото) + print-agent (Python) + OpenAI-совместимый API за абстракцией. Deploy — Docker Compose.

---

## 4. Архитектура модулей + source of truth

### 4.1. Модули (монорепо)

```
apps/
  web/            Next.js App Router, TS, Tailwind, shadcn/ui, PWA (manifest + service worker)
  api/            FastAPI: auth, repairs, chat, prices, stats, callcenter, admin, public, ws
  print-agent/    Python: опрашивает очередь, печатает PDF через драйвер ОС (L3250)
packages/
  shared/         константы статусов/ролей, типы (генерируются из OpenAPI), валидаторы
```

### 4.2. Source of truth (важно — стек Python)

- **Контракт DTO:** Pydantic-модели в `apps/api` — единый источник истины.
- FastAPI автоматически генерирует **OpenAPI** → фронт получает TS-типы через `openapi-typescript` (+ опционально клиент `openapi-fetch`). Zod на фронте — только для **форм** (приёмка), не дублирует контракт API.
- **Константы статусов/ролей** — в `packages/shared` (один файл, копируется/синхронизируется с Python-enum, либо кодгеном).
- Бизнес-правила (срок хранения, тексты, SLA, тексты бланка) — **в `settings` в БД**, не в коде.

### 4.3. Потоки

- **Realtime:** нативный WebSocket (FastAPI поддерживает WS из коробки) → эндпоинт `/ws` для чата + push-уведомлений. Socket.IO не нужен (лишняя зависимость поверх Python).
- **Очередь печати:** `POST /repairs/:id/print` → API рендерит PDF-бланк → запись в `print_jobs` (status=queued) → print-agent (на точке) забирает PDF → печать через команду ОС (`lp`/Windows-драйвер) → статус job → событие в `repair_events` + аудит. ESC/POS (термо) — опция позже.
- **Фото:** multipart в MinIO/S3, в БД только ключ объекта.
- **AI:** все вызовы через единый интерфейс `ai/providers/*` (OpenAI-совместимый), промпты и ответы пишутся в `ai_runs` (аудит).

### 4.4. Физическая топология (Docker Compose, MVP)

```
web (Next)  →  api (FastAPI)  →  postgres
                  │                redis
                  ├──→ minio (фото)
                  └──→ print-agent (в LAN на точке) → Epson L3250 (драйвер ОС, A4)
```

print-agent ставится на машину в той же LAN, что и принтер (Windows-ящик у стойки или Raspberry Pi): опрашивает очередь через API, скачивает PDF и печатает через драйвер ОС (для L3250).

---

## 5. ER-модель таблиц

Типы: `uuid` (PK), `ts` (timestamptz), `text`, `int`, `numeric`, `jsonb`, `bool`, `enum` (varchar + check).

### users
| поле | тип | примечание |
|---|---|---|
| id | uuid PK | |
| name | text | |
| email | text unique | |
| phone | text | |
| password_hash | text | |
| role | enum | `admin|manager|operator|master|callcenter` |
| city_id | uuid FK→cities | ограничение доступа |
| branch_id | uuid FK→branches | |
| active | bool | |
| created_at / updated_at | ts | |

### cities / branches
| таблица | поля |
|---|---|
| cities | id, slug, name, timezone |
| branches | id, city_id FK, name, address, phone, print_config jsonb (printer ip/port/codepage/width), active |

### clients
| поле | тип | примечание |
|---|---|---|
| id | uuid PK | |
| full_name | text | |
| phone | text | **индекс** |
| phone_norm | text | нормализованный для поиска, уникальный в рамках |
| consent_pdn_at | ts | согласие на ПДн |
| consent_storage_at | ts | согласие «хранение 3 мес» |
| deleted_at | ts | процедура удаления (152-ФЗ) |
| created_at / updated_at | ts | |

### repairs
| поле | тип | примечание |
|---|---|---|
| id | uuid PK | |
| number | text unique | `TV-{city}-{YYYY}-{NNNNN}` |
| public_token | text unique | 128+ бит, криптослучайный, **не enumerable** |
| city_id / branch_id | uuid FK | |
| client_id | uuid FK | |
| device_type | text | ТВ/монитор/аудио/другое |
| brand / model / serial | text | |
| complectation | jsonb | чекбоксы + своё |
| fault_client | text | со слов клиента |
| fault_master | text | диагноз мастера |
| condition_notes | text | внешний вид/повреждения |
| accepted_by | uuid FK→users | |
| master_id | uuid FK→users nullable | |
| status | enum | настраиваемый справочник |
| eta_days | int | |
| eta_source | enum | `manual|stats|ai` |
| price_min / price_max / price_final | numeric | |
| accepted_at / ready_at / issued_at | ts | |
| storage_until | ts | accepted_at + storage_months |
| print_count | int | |
| source | enum | `walkin|call|site` |
| idempotency_key | text unique | для POST /repairs |

**Индексы:** phone (через clients), number, status, master_id, city_id, accepted_at, public_token.

### complectation_items / repair_complectation
| таблица | поля |
|---|---|
| complectation_items | id, name (ПДУ/кабель/подставка…), sort |
| repair_complectation | repair_id FK, item_id FK (m2m) |

### repair_photos
| поле | тип |
|---|---|
| id | uuid PK |
| repair_id | uuid FK |
| object_key | text (S3) |
| caption | text |
| uploaded_by | uuid FK→users |
| created_at | ts |

### repair_events (timeline)
| поле | тип | примечание |
|---|---|---|
| id | uuid PK | |
| repair_id | uuid FK | индекс |
| type | enum | `status_change|comment|print|call|price|photo|assign|notify` |
| actor_id | uuid FK→users | |
| data | jsonb | from_status, to_status, message, price delta… |
| created_at | ts | |

### price_items / price_item_history
| поле | тип |
|---|---|
| price_items | id, device_type, brand, model_or_line, fault, city_id, price_min, price_max, price_avg, typical_days, source, active |
| price_item_history | id, price_item_id FK, changed_by, changed_at, diff jsonb |

### chat_channels / chat_messages / chat_channel_members
| таблица | поля |
|---|---|
| chat_channels | id, slug (#общий), name, kind enum `public|private` |
| chat_channel_members | channel_id FK, user_id FK |
| chat_messages | id, channel_id FK, author_id FK, text, repair_ref (номер), created_at, edited_at |

### notifications
| поле | тип |
|---|---|
| id | uuid PK |
| user_id | uuid FK |
| type | enum `new_acceptance|ready|overdue_storage|call_task|status_change` |
| title / body | text |
| repair_id | uuid FK nullable |
| read_at | ts |
| created_at | ts |

### print_jobs
| поле | тип |
|---|---|
| id | uuid PK |
| repair_id | uuid FK |
| template_id | text | (из print-templates) |
| payload | jsonb |
| status | enum `queued|sent|done|failed` |
| attempts / error | int / text |
| branch_id | uuid FK | какой агент печатает |
| created_at / sent_at | ts |

### settings
| поле | тип |
|---|---|
| id / key / value | uuid / text unique / jsonb |
| description | text |

Ключи: `storage_months=3`, `legal_text`, `sla_defaults`, `brand`, `sms_enabled`, `print_mode` (escpos|pdf).

### ai_runs / audit_log
| таблица | поля |
|---|---|
| ai_runs | id, kind (predict_eta|summary|anomaly), input jsonb, output jsonb, model, tokens, latency_ms, created_at |
| audit_log | id, actor_id, action, entity, entity_id, meta jsonb, ip, created_at |

### print_templates
| поле | тип |
|---|---|
| id | uuid PK |
| name | text | бланк клиента / корешок |
| body | text | Handlebars/JSON шаблон |
| is_default | bool |

---

## 6. API draft MVP

Все роуты под `/api` (или v1). Аутентификация: JWT access + refresh (httpOnly cookie для web). Роли проверяются на каждом endpoint. `Idempotency-Key` на `POST /repairs`.

```
POST   /auth/login               # → set-cookie refresh, body access_token
POST   /auth/refresh
GET    /me

# Чат + realtime
GET    /chat/channels
GET    /chat/channels/:id/messages
POST   /chat/channels/:id/messages      # body: text, repair_ref?
WS     /ws                              # события: message, notification

# Приёмка и ремонты
POST   /repairs                         # Idempotency-Key; auto: number, public_token, storage_until
GET    /repairs                         # ?status=&master_id=&city_id=&q=&page=
GET    /repairs/:id
PATCH  /repairs/:id                     # статус, мастер, цены, eta…
POST   /repairs/:id/photos
POST   /repairs/:id/events              # комментарий / лог звонка
POST   /repairs/:id/print               # → print_jobs + RQ
GET    /repairs/by-number/:number

# Публичная страница QR (limited DTO, noindex, rate-limit)
GET    /public/r/:token

# Прайс
GET    /prices                          # ?type=&brand=&model=&city=&fault=
POST   /prices                          # admin
PATCH  /prices/:id                      # admin
POST   /prices/import                   # admin, CSV/Excel (позже)

# Статистика + AI
GET    /stats/overview
GET    /stats/tiles                     # «курс ремонта»: ?type=&brand=&model=&city=
POST   /ai/predict-eta
POST   /ai/weekly-summary

# Call-центр
GET    /callcenter/queue                # ?kind=agree|ready|overdue

# Админ
GET/POST/PATCH /admin/cities
GET/POST/PATCH /admin/branches
GET/POST/PATCH /admin/users
GET/PUT        /admin/settings
GET/POST/PATCH /admin/print-templates
```

Ключевые DTO-ограничения:
- `/public/r/:token` — только публичные поля (статус, техника, даты, «как обычно», контакты); **без** `fault_master`, себестоимости, внутренних комментариев.
- Маскирование телефона для ролей без доступа к клиенту (например, callcenter видит полный, оператор — полный, но в `/public` телефон не отдаём вообще).

---

## 7. Текстовые wireframes

### 7.1. Логин
```
┌─────────────────────────────┐
│        MSB           │
│                             │
│  [ Телефон или email   ]    │
│  [ Пароль             ]     │
│                             │
│  [      Войти →       ]     │  ← крупная кнопка (≥44px)
│                             │
│  Забыли пароль?             │
└─────────────────────────────┘
```
После логина оператор попадает сразу на **Приёмку** (не на дашборд).

### 7.2. Чат (каналы)
```
┌─ Каналы ─────────────┬─ #приёмка ────────────────┐
│ #общий        (12)   │  [система] Принято        │
│ #приёмка      (5) ▸  │    TV-MSK-2026-01482      │
│ #мастера      (3)    │    Samsung 55"            │
│ #callcenter   (7)    │  [Аня] клиент просил ...  │
│                      │  [Сергей] #TV-MSK-01482 ▸ │ ← превью ремонта
│                      │ ┌─────────────────────┐   │
│                      │ │ Введите сообщение…  │   │
│                      │ └─────────────────────┘   │
└──────────────────────┴───────────────────────────┘
```

### 7.3. Приёмка (4 шага, mobile-first)
```
Шаг 1 — Клиент            Шаг 2 — Техника/комплект
┌───────────────────┐    ┌───────────────────┐
│ ① Клиент          │    │ ② Техника         │
│ ФИО* [          ] │    │ Тип: [ТВ][Монитор] │
│ Тел* [          ] │    │   [Аудио][Другое]  │
│ ✓ Согласие на ПДн │    │ Марка (chips):     │
│ ✓ Хранение 3 мес  │    │ [Samsung][LG][Xiaomi]│
│   [Далее →]       │    │ Модель [        ]  │
└───────────────────┘    │ Серийник [       ] │
                         │ Комплект:          │
                         │ ☑ ПДУ ☑ Кабель     │
                         │ ☐ Подставка ☐ Своё │
                         │   [Далее →]        │
                         └───────────────────┘

Шаг 3 — Фото/мастер       Шаг 4 — Подтверждение
┌───────────────────┐    ┌───────────────────┐
│ ③ Фото и мастер   │    │ ④ Подтверждение   │
│ Внешний вид:      │    │ Клиент: Иванов    │
│ [      ]  [📷 Фото]│    │ ТВ Samsung 55"   │
│ Неисправность:    │    │ Комплект: ПДУ, каб│
│ [   со слов...   ]│    │ Мастер: в очередь │
│ Мастер:           │    │ ETA: 6 дн (авто) │
│ [в очередь ▾]     │    │ Хранение: 3 мес ✓ │
│   [Далее →]       │    │ ┌────────────────┐│
└───────────────────┘    │ │ Принять и      ││
                         │ │ печатать       ││  ← одна главная кнопка
                         │ └────────────────┘│
                         └───────────────────┘
```

### 7.4. Успех + печать
```
┌─────────────────────────────┐
│         ✓ Принято           │
│                             │
│      TV-MSK-2026-01482      │  ← огромный номер
│                             │
│  [ 🖨 Печатать ещё раз ]    │
│  [  ➕ Новая приёмка  ]     │
│  [  🔗 Открыть карточку ]   │
└─────────────────────────────┘
```
Статус печати: `Напечатано` / `Печать…` / `Ошибка — PDF` (fallback-кнопка).

### 7.5. Карточка ремонта (единый экран call-центра/мастера)
```
┌──────────────────────────────────────────────┐
│ TV-MSK-2026-01482      [Статус: Диагностика ▾]│
│ Клиент: Иванов И.  +7 900 ... (🔒 маскиров.) │
│ ТВ · Samsung · UE55 · SN: xxx   [фото][фото] │
│ Комплект: ПДУ, кабель                        │
│ Неиспр. (клиент): «не включается»            │
│ Диагноз (мастер): _____________              │
│ Мастер: [Сергей ▾]  ETA: 6 дн (ai, 0.78)     │
│ Цена: 5 000 – 7 400 ₽   Принято: 26.08 14:02 │
│ Хранение до: 26.11        Печать: 2×         │
│ ──────────────────────────────────────────── │
│ Timeline:                                    │
│  14:02 принято · 14:03 бланк · 15:10 звонок  │
│  [💬 Комментарий]  [🖨 Печать]  [📷 Фото]    │
└──────────────────────────────────────────────┘
```

### 7.6. Публичная страница `/r/{token}` (QR)
```
┌──────────────────────────────────────────────┐
│        Сервисный центр «MSB»          │
│          Ваш ремонт TV-MSK-2026-01482        │
│                                              │
│  Статус:  ● Диагностика                      │
│  Прогресс: ▓▓░░░░░░ (2/7)                    │
│                                              │
│  Принято:      26.08.2026                    │
│  План:         6 дней                        │
│  Техника:      ТВ Samsung 55"                │
│  Комплект:     ПДУ, кабель                   │
│                                              │
│  ⚠ Хранение 3 месяца: <полный текст>        │
│                                              │
│  «Как обычно у нас в городе: ТВ — 6.2 дн»    │
│                                              │
│  ☎ Телефон: +7 (…)  (noindex, rate-limited)  │
└──────────────────────────────────────────────┘
```

### 7.7. Дашборд «курс ремонта»
```
┌──────────────────────────────────────────────┐
│ TV · Samsung · 55" · Москва                  │
│  Срок  6.2 дн  ▾0.4   n=128                  │
│  Чек   7 400 ₽  ▴210                         │
│  AI: чаще подсветка/БП · ETA уверенность 0.78│
├──────────────────────────────────────────────┤
│ [Срок] [Чек] [Загрузка] [SLA %]  (перекл.)   │
│ ┌──────────────────────────────────────────┐ │
│ │ график: медиана / p90 / тренд            │ │
│ └──────────────────────────────────────────┘ │
│ Неделя мастеров: …   Аномалии: …             │
└──────────────────────────────────────────────┘
```

---

## 8. План 4–6 недель + Definition of Done

Ритм: каждая итерация — демо «можно потыкать пальцем на телефоне».

| Итерация | Срок | Содержание | DoD |
|---|---|---|---|
| **0 — Фундамент** | 1 нед | монорепо, Docker Compose, Postgres, auth (JWT+refresh, роли), модели User/City/Branch/Client/Repair/Timeline, админ юзеров/городов/точек, README, .env.example | `docker compose up` поднимает стек; логин по ролям; сиды городов/точек/юзеров |
| **1 — Чат** | 1 нед | каналы, сообщения, WS realtime, упоминание ремонта по номеру, базовые in-app уведомления | сообщение в канале видно у всех в realtime; `#TV-MSK-01482` превращается в превью |
| **2 — Приёмка + печать** | 1 нед | PWA-форма приёмки (4 шага), создание Repair+Client, генерация номера, PDF-бланк (A4) + print-agent, «Повторить печать», QR → public token | оператор с телефона создаёт приёмку < 1 мин; бланк на Epson L3250 (PDF); **кириллица читается** |
| **3 — QR-страница** | 0.5 нед | публичный статус, техника/комплект, условия 3 мес, «как обычно» по городу, контакты | QR открывает страницу; нет внутренних данных; noindex+rate-limit |
| **4 — Доска ремонтов + роли** | 1 нед | канбан/список, фильтры, смена статуса, очередь call-центра, фото/комменты/назначение мастера | мастер видит только свои; call-центр ведёт очередь; статус меняется с timeline |
| **5 — Прайс API** | 0.5 нед | CRUD цен, вилка по типу/бренду/городу, подсказка в форме/диагностике | GET /prices отдаёт вилку; подсказка в приёмке |
| **6 — Дашборд + AI** | 1 нед | плитки «курс ремонта», медиана/p90/SLA/загрузка, AI predict-eta + weekly-summary, анти-галлюцинация | средний срок по городу+типу; AI-прогноз **или** честный «мало данных» при n < порога |

**Итого: ~6 недель** до MVP по DoD из ТЗ.

---

## 9. Риски (явно)

| Риск | Уровень | Митигация |
|---|---|---|
| **Печать / кириллица** (A4 PDF на L3250) | 🟡 средний | PDF через ReportLab + DejaVuSans (кириллица гарантирована); print-agent изолирован; smoke-тест «русский текст на реальном принтере» в итерации 2; код code page (CP866) понадобится только если позже подключим термопринтер |
| **Realtime (WS)** | 🟡 средний | нативный WS в FastAPI без Socket.IO; fallback — polling/refetch на каналах |
| **AI-галлюцинации** | 🟡 средний | порог `n`, явный вывод «мало данных», лог `ai_runs`, абстракция провайдера |
| **ПДн / 152-ФЗ** | 🔴 высокий | согласие при приёмке, маскирование телефона, аудит, `deleted_at` + процедура удаления, секреты только в env, backup Postgres |
| **Идемпотентность приёмки** | 🟡 средний | `Idempotency-Key` + unique-индекс; повторный submit не плодит дубликаты |
| **Принтер Epson L3250** | 🟢 низкий | A4 струйный, печать через драйвер ОС (print-agent командой `lp`/Windows); точная модель подтверждена заказчиком |
| **Плохой интернет на точке** | 🟡 низкий (v1 online) | отложенный outbox на клиенте в итерации позже |

---

## 10. Скелет репо (предложение, код — после «ОК»)

```
system/
├── README.md                    # запуск, тестовые логины, как подключить print-agent
├── .env.example
├── docker-compose.yml           # postgres, redis, minio, api, web, print-agent
├── apps/
│   ├── web/                     # Next.js (App Router) + TS + Tailwind + shadcn/ui + PWA
│   │   ├── app/  components/  lib/  public/manifest.webmanifest
│   │   └── generated/           # TS-типы из OpenAPI (openapi-typescript)
│   ├── api/                     # FastAPI
│   │   ├── app/
│   │   │   ├── main.py          # FastAPI app + lifespan
│   │   │   ├── core/            # config, security (JWT), deps (роли)
│   │   │   ├── db/              # SQLAlchemy models, миграции (Alembic)
│   │   │   ├── schemas/         # Pydantic DTO (source of truth)
│   │   │   ├── routers/         # auth, chat, repairs, prices, stats, callcenter, admin, public
│   │   │   ├── services/        # бизнес-логика (repairs, numbering, print, stats, ai)
│   │   │   ├── ws/              # WebSocket manager
│   │   │   └── ai/providers/    # OpenAI-совместимый адаптер
│   │   └── tests/
│   └── print-agent/             # Python: PDF → драйвер ОС (Epson L3250, A4)
│       └── agent.py
├── packages/
│   └── shared/                  # константы статусов/ролей, типы
└── docs/
    └── msb-kickoff.md    # этот документ
```

**README (содержание на старте):** как поднять (`docker compose up`), тестовые логины по ролям (`admin@…/operator@…/master@…/call@…`), настройка print-agent (IP/порт принтера Epson, code page, ширина ленты), как пройти сценарий «приёмка → печать → QR».

---

## Следующий шаг

Жду **«ОК»** (и, желательно, ответы на 4 открытых вопроса из пункта 1, прежде всего — **точная модель Epson**). После ОК кодирую **Итерацию 0 (фундамент) + Итерацию 1 (чат)**, как задано в суперпромпте.
