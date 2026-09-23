# Спецификация формата обмена данными MSB (JSON / ZIP Schema)

Версия формата: **1.0**. Файл используется для резервных копий MSB, для
импорта из старых систем и для интеграции внешних проектов.

Реализация: `apps/api/app/services/backup.py`. Интерфейс: админка
**Настройки → 💾 Данные** или JSON-API `GET /api/admin/backup/export`,
`POST /api/admin/backup/import` (роль `admin`).

---

## 1. Контейнер

```
msb_backup.zip
├── meta.json          метаданные (дата, автор, число записей по таблицам)
├── msb_export.json    данные (см. ниже); допустимое имя — data.json
└── media/…            файлы фотографий ремонтов (необязательно)
```

Импорт принимает и голый `msb_export.json` без архива. Кодировка — UTF-8.

## 2. Корень `msb_export.json`

```
version: "1.0"                      версия формата данных
exported_at: "YYYY-MM-DD HH:MM:SS"  время формирования экспорта (UTC)
tables: { <таблица>: [ записи ] }   см. раздел 3
```

Соглашения:

| Тип         | Правило |
|-------------|---------|
| Даты        | `YYYY-MM-DD HH:MM:SS` в UTC. Импорт также понимает ISO 8601 со смещением (`2026-09-18T00:15:27+05:00`), `YYYY-MM-DD`, `DD.MM.YYYY`, unix-timestamp. |
| Деньги      | целые копейки/тенне в полях `*_cents` (500 ман = `50000`). |
| Флаги       | `1` / `0` (принимаются также `true`/`false`, `"1"`/`"0"`). |
| JSON-поля   | строка с JSON (`"[\"remote\"]"`); принимается и готовый массив/объект. |
| `id`        | любой тип: UUID, целое (`1`), строка (`c-100`). Внутри файла ссылки (`client_id`, `repair_id`, `donor_id`, `user_id`) должны совпадать с `id` своих таблиц. |
| Синонимы    | где указано `a / b` — принимается любое из имён. |

## 3. Таблицы

Обязательных таблиц нет — отсутствующие пропускаются. Каждая таблица —
массив объектов (принимается также `{ "rows": [...] }` и `{ id: объект }`).

### 3.1 `clients` — клиенты

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | int/str/uuid | идентификатор |
| `name` / `full_name` | str | ФИО клиента |
| `phone` | str | номер телефона (`+993XXXXXXXX`; принимаются местные `8 61 …`, `61 …`) |
| `phone_norm` | str | нормализованный номер (`99361234567`); если нет — вычисляется |
| `created_at`, `updated_at` | str | даты |
| `is_archived` | int | `1` — клиент в архиве (в MSB — `deleted_at`) |
| `deleted_at` | str/null | дата удаления (альтернатива `is_archived`) |

Сопоставление при импорте: по `id` (если UUID), иначе по `phone_norm`.

### 3.2 `repairs` — ремонты

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | int/str/uuid | идентификатор |
| `number` | str | номер заказа (`TV-2026-001`); если пусто — генерируется |
| `public_token` | str | токен публичной QR-страницы; если пусто/занят — генерируется |
| `client_id` | | ссылка на `clients.id` (**обязательно**) |
| `category` / `device_type` | str | категория техники: `Телевизоры`, `Мониторы`, `ТВ-приставки`, `Компьютеры`, `Бытовая техника`, `Другое`. Понимаются синонимы (`Телевизор`, `ТВ`, `Ноутбуки`→`Компьютеры`, …); неизвестное → `Другое` с предупреждением |
| `brand`, `model` | str | производитель, модель |
| `serial_number` / `serial` | str | серийный номер |
| `equipment_json` | str(JSON) | комплектация: коды `remote`, `power_cable`, `legs`, `wall_mount`, `box_ir_eye`, `box`, `all_in_box`, `tv_only`, … или произвольные подписи |
| `equipment_other` | str | комплектация текстом через запятую |
| `complectation` | obj | сырой словарь MSB (`{"items":[…]}` или `{"Пульт":true}`) — приоритетнее `equipment_json` |
| `condition_json` | str(JSON) | состояние: `screen_scratches`, `body_scratches`, `broken_parts`, `other_service` |
| `condition_other` | str | состояние текстом |
| `fault_client` | str | заявленная неисправность |
| `diagnosis` / `fault_master` | str | диагноз мастера |
| `work_done` | str | выполненная работа |
| `status` | str | этап. MSB хранит пять: `Новый`, `На диагностике`, `В работе`, `Ждёт запчастей`, `Завершён`. Понимаются `Принят`, `Диагностика`, `В ремонте`, `Готово к выдаче`, `Выдано`, `Закрыт`, `new`/`done`/`issued` и т.д. Неизвестный → `Новый` с предупреждением |
| `price_min_cents`, `price_max_cents`, `price_final_cents` | int | вилка и итоговая цена |
| `paid_cents` | int | сколько оплачено; если в файле нет `payments`, превращается в один платёж кассы |
| `is_paid` / `payment_mark` | int | флаг «оплачено» |
| `master_payout_cents`, `cost_cents` | int | выплата мастерам, расходы |
| `warranty_text` | str | гарантия текстом (`90 дней`, `3 aý`) |
| `warranty_start`, `warranty_until` | date | даты гарантии; при отсутствии `warranty_text` из них считается срок |
| `responsible_master_id` (+ `responsible_master_name`) | | основной мастер (`users.id` или старый int-id; по имени, если id неизвестен) |
| `accepted_by_id` (+ `accepted_by_name`) | | кто принял; неизвестный сотрудник создаётся выключенным |
| `is_delivery`, `delivery_district`, `delivery_comment` | | доставка |
| `delivery_person`, `delivery_phone`, `delivery_fee_cents` | | курьер (имя уходит в комментарий доставки) |
| `secondary_name` / `contact2_name`, `secondary_phone` / `contact2_phone`, `secondary_relation` / `contact2_relation` | str | второй контакт |
| `photos_json` | str(JSON) | `[{"object_key": "...", "thumb_key": "...", "caption": "..."}]`; записи создаются только если файл есть в `media/` |
| `created_at` / `accepted_at`, `updated_at` | str | приём |
| `finished_at` / `ready_at` | str | готовность |
| `issued_at` | str | выдача клиенту (проставляется автоматически для статусов `Выдано`/`Закрыт`) |
| `notified_at` | str | последнее SMS клиенту |
| `deleted_at` | str/null | удалённые (`deleted_at` не пустой) при импорте пропускаются |

Сопоставление: по `id` (если UUID), иначе по `number`.

### 3.3 `repair_masters` — мастера и помощники

| Поле | Описание |
|------|----------|
| `repair_id` | ссылка на `repairs.id` |
| `user_id` (+ `display_name`) | сотрудник; неизвестный создаётся выключенным с ролью `master` |
| `assignment_role` | `master` (основной) или `assistant` (помощник) |
| `reward_cents` | вознаграждение; если у ремонта нет `master_payout_cents`, суммируется в него |
| `position` | порядок в бланке (необязательно) |

### 3.4 `repair_parts` — запчасти и расходы

| Поле | Описание |
|------|----------|
| `id`, `repair_id` | |
| `name` | название (ищется в складе по имени, иначе создаётся позиция без остатка) |
| `part_id` | ссылка на `parts.id` (необязательно) |
| `quantity` / `qty` | количество |
| `unit_cost_cents` / `price_cents` | цена за единицу |
| `is_manual` | `1` — внесена вручную, не со склада (по умолчанию 1) |
| `created_at` | |

### 3.5 `repair_history` — журнал событий ремонта

| Поле | Описание |
|------|----------|
| `id`, `repair_id` | |
| `event_type` / `type` | `status_change`, `comment`, `print`, `call`, `price`, `photo`, `assign`, `notify` |
| `actor_user_id` (+ `actor_name`) | кто |
| `comment` | текст; для `status_change` допустим вид `Старый → Новый` |
| `details_json` | произвольные детали (`{"from": ..., "to": ...}`) |
| `created_at` | |

Дедупликация: по UUID события либо по (тип, время, текст, from/to).

### 3.6 `repair_number_aliases` — старые номера

`{ "old_number": "MSB-00123", "repair_id": <repairs.id> }` — после импорта
переход `/repairs/by-number/MSB-00123` открывает карточку.

### 3.7 `donor_units` / `donor_parts` — доноры

`donor_units`: `id`, `brand`, `model`, `serial_number`, `board_number`, `comment`,
`created_by_id`/`created_by_name`, `created_at`, `updated_at`
(серийник и номер платы сохраняются в комментарии).

`donor_parts`: `id`, `donor_id`, `name`, `quantity`, `panel_number`,
`price_cents`, `comment`, `created_at`.

### 3.8 `sms_log` — журнал SMS

| Поле | Описание |
|------|----------|
| `id` | |
| `repair_id` | ремонт или пусто (тест шлюза, чат) |
| `phone` | получатель |
| `text` / `body` | текст |
| `kind` / `type` | `ready`, `pickup_reminder`, `master_assign`, `test`, `staff_chat`, … |
| `ok` (1/0) или `status` (`sent`/`failed`) | результат |
| `detail` | ответ шлюза / ошибка |
| `actor_user_id` / `created_by_id` | кто отправил |
| `created_at` | |

SMS по ремонту становятся событиями `notify` в истории ремонта; без ремонта —
записями журнала аудита `sms.sent`.

### 3.9 `print_log` — журнал печати

| Поле | Описание |
|------|----------|
| `id`, `repair_id` | ремонт или пусто (тест принтера) |
| `kind` | `blank`, `label`, `client_label`, `test` |
| `target` | адрес принтера |
| `ok` (1/0) или `status` (`done`/`failed`) | результат |
| `detail` / `error` | |
| `created_by_id` / `created_by_name`, `created_at` | |

Печать по ремонту → задание `print_jobs` (статус `done`/`failed`, без PDF);
без ремонта → журнал аудита `print.log`.

### 3.10 `app_settings` — настройки

`{ "key": "sms_server", "value_json": "{...}", "description": "...", "updated_at": "..." }`.
Ключи `ip_control` и `data_migrations` из файла **не применяются**
(чужой белый список IP заблокировал бы администратора).

### 3.11 Служебные таблицы (экспортируются MSB, для импорта необязательны)

`users`, `cities`, `branches`, `payments`, `repair_part_orders`, `parts`,
`price_items`, `equipment`. Нужны, чтобы восстановление собственной копии на
чистой базе было полным (сохраняются id, пароли сотрудников, платежи кассы).

## 3.12 Отдельный файл учётных записей — `msb_users.json`

Страница **Сотрудники → 💾 Учётные записи** или API
`GET /api/admin/backup/users/export[?passwords=0]`,
`POST /api/admin/backup/users/import` (`deactivate_missing=1`, `dry_run=1`).

```
version: "1.0"
kind: "users"
exported_at, exported_by
passwords_included: true|false
tables:
  users[]     id, name, email, phone, telegram, role, extra_roles_json,
              permissions_json, active, password_hash|null, city_slug,
              branch_name, created_at, updated_at
  cities[]    id, slug, name, timezone
  branches[]  id, city_slug, name, address, phone, active
```

Импорт принимает этот файл, полную копию (`msb_backup.zip` / `msb_export.json`
— берётся только `users` + `cities` + `branches`) или простой список
`[{"name", "email", "role", "password", "active"}]`, набранный вручную
(`password` — открытый текст, хэшируется при загрузке; `role` любого регистра;
неизвестная роль → `operator` с предупреждением).

Правила: сопоставление по `id` (UUID) или `email`; существующие обновляются
(имя, роли, права, статус, пароль — если есть в файле), новые создаются;
без пароля — выключенными, список показывается в отчёте. Того, кто выполняет
импорт, нельзя отключить или понизить в правах. `deactivate_missing`
отключает сотрудников, которых нет в файле (удаления нет: история ремонтов
ссылается на сотрудников).

## 4. Правила импорта

* **Режимы:** `merge` (по умолчанию) — добавить/обновить; `replace` — сначала
  удалить клиентов, ремонты со всем содержимым и склад разбора, затем загрузить.
  Сотрудники, настройки, прайс и склад запчастей в `replace` не удаляются.
* **Идемпотентность:** повторная загрузка того же файла ничего не дублирует.
* **Транзакция:** любая ошибка откатывает весь импорт; в тексте ошибки
  указываются таблица и запись.
* **Сотрудники:** неизвестные `accepted_by_id` / `user_id` сопоставляются по
  имени; если не найдены — создаются **выключенными** без пароля (список
  показывается в отчёте). Один человек, который и принял, и чинит, получает
  роли `operator` + `master`.
* **Проверка без записи:** `POST /api/admin/backup/import` с `dry_run=1`
  возвращает состав файла, ничего не меняя.

## 5. Минимальный пример файла внешней системы

```json
{
  "version": "1.0",
  "exported_at": "2026-09-23 12:00:00",
  "tables": {
    "clients": [
      {"id": 1, "name": "Ахмед Ахмедов", "phone": "+99361000000",
       "created_at": "2026-01-01 10:00:00", "is_archived": 0}
    ],
    "repairs": [
      {"id": 10, "number": "TV-2026-001", "category": "Телевизоры",
       "brand": "SAMSUNG", "model": "QE55Q70", "serial_number": "SN12345",
       "equipment_json": "[\"remote\"]", "fault_client": "Не включается",
       "work_done": "Замена блока питания", "status": "Завершён",
       "price_final_cents": 50000, "is_paid": 1, "client_id": 1}
    ],
    "repair_masters": [
      {"repair_id": 10, "user_id": 7, "display_name": "Мастер Ахмед",
       "assignment_role": "master", "reward_cents": 15000}
    ],
    "repair_parts": [
      {"id": 1, "repair_id": 10, "name": "ШИМ контроллер",
       "quantity": 1, "unit_cost_cents": 3500}
    ],
    "repair_history": [
      {"id": 1, "repair_id": 10, "event_type": "comment",
       "comment": "Ремонт завершён", "created_at": "2026-01-01 18:00:00"}
    ],
    "donor_units": [], "donor_parts": [], "sms_log": [], "print_log": []
  }
}
```

Реальный пример выгрузки старой базы: `docs/msb_export_20260923_173848.json`
(используется в `tests/test_backup.py`).
