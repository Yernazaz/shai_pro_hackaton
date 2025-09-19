# NQL CRM — NL→SQL ассистент для салона красоты

NQL CRM превращает вопросы на русском языке в корректные SQL-запросы к рабочей базе салона красоты. Решение развёртывается как REST API и Telegram-бот, поэтому администратор может спросить «выручка за всё время» или «топ сотрудников по выручке», а система сама подберёт SQL, выполнит его в PostgreSQL и вернёт бизнес-резюме.

---

## Основные возможности

- **Естественный язык → SQL.** Gemini 1.5 Pro формирует план запроса и финальный SQL с учётом разрешённых таблиц и доменных эвристик.
- **Две точки входа.** REST API (`POST /query`) и Telegram-бот с памятью и командой `sql` для просмотра последнего запроса.
- **Аналитический ответ.** После выполнения SQL LLM строит текстовую сводку, а Telegram-бот показывает её с безопасным форматированием и рекомендациями.
- **Безопасность данных.** Только `SELECT`/CTE, whitelisted таблицы, авто-LIMIT, маскирование PII, канонические правила для «выручки».
- **Контекстные диалоги.** Pending-хинты и кратковременная память в Redis (есть in-memory fallback) позволяют обрабатывать уточнения.

---

## Как устроен пайплайн

```
Запрос (REST / Telegram)
  ↓
Pre-processing: очистка, добавление контекста из pending_state
  ↓
Planner (app/pipeline/planner.py): Gemini → PlanOut JSON (нормализованный вопрос, SQL, эвристики)
    • проверка SQL на пустоту и обязательное использование crm_payments для запросов о выручке
  ↓
SQL Executor (app/db/execute_sql_query.py): psycopg2 (read-only), фильтр таблиц, авто LIMIT, маскирование PII
  ↓
Analyzer (app/pipeline/analyzer.py): Gemini → AnalysisOut JSON, бизнес-резюме без запроса уточнений
  ↓
Response Formatter (app/utils/response_formatter.py): текст для пользователя + follow-up подсказки
```

Ключевые компоненты:

| Компонент | Модуль | Задача |
|-----------|--------|--------|
| Планировщик | `app/pipeline/planner.py` | Формирует JSON по контракту `PlanOut`, нормализует сущности и гарантирует ненулевой SQL. |
| Контроллер | `app/pipeline/controller.py` | Управляет итерациями (до 3 попыток), исполняет SQL, агрегирует телеметрию и память. |
| Анализатор | `app/pipeline/analyzer.py` | Преобразует результаты запроса в человеко-читаемую сводку по схеме `AnalysisOut`. |
| SQL безопасность | `app/db/execute_sql_query.py` | Проверка ключевых слов, whitelisted таблиц, auto-limit, маскирование персональных данных. |
| LLM клиент | `app/utils/llm_client.py` | Обёртка над Google Generative AI (Gemini), единый формат ответов. |
| Контекст | `app/utils/context_store.py` | Хранение pending состояний в Redis или in-memory fallback. |

Промпты лежат в `app/pipeline/prompts/`: `plan_v1.txt` описывает правила генерации SQL, `analysis_v1.txt` — структуру бизнес-ответа.

---

## Структура репозитория

```
app/
  pipeline/          # Планировщик, контроллер, анализатор, промпты
  db/                # Вспомогательные функции для выполнения SQL
  utils/             # LLM клиент, контекст, логирование, генераторы ответов
  services/          # Сервисные функции (например, предзагрузка имён сотрудников)
  telegram_bot.py    # Асинхронный PTB v21 бот
  main.py            # FastAPI-приложение с /query и /healthz
data/
  schema_metadata.json  # Описание таблиц для подсказки модели
db/init/             # SQL-скрипты для поднятия демо-данных
docker-compose.yml   # API + бот + PostgreSQL для демо
requirements.txt
README.md
```

---

## Подготовка окружения

### Требования

- Python 3.11+
- PostgreSQL 15 (локально или в Docker)
- API-ключ Gemini (Google AI Studio / Vertex AI)
- (опционально) Redis для хранения pending состояний — при отсутствии используется fallback в памяти процесса

### Локальный запуск

```bash
git clone https://github.com/<your-org>/nql_crm.git
cd nql_crm
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# заполните GEMINI_API_KEY, реквизиты PostgreSQL и TELEGRAM_BOT_TOKEN (если нужен бот)

# разверните демо-данные (опционально)
psql -h localhost -U postgres -f db/init/01_schema.sql
psql -h localhost -U postgres -f db/init/02_sample_data.sql

# запустите REST API
uvicorn app.main:app --reload

# (по желанию) Telegram-бот
python app/telegram_bot.py
```

### Docker Compose

```bash
cp .env.example .env
export GEMINI_API_KEY=AIza...
docker compose up --build
```

Контейнеры `nqlcrm_api` и `nqlcrm_bot` шарят один исходный код и подключаются к Postgres (`nqlcrm_db`). API доступен по `http://localhost:9000`.

---

## Конфигурация

| Переменная | Назначение | Значение по умолчанию |
|------------|------------|------------------------|
| `GEMINI_API_KEY` | Ключ к Google Generative AI | — (обязательно) |
| `GEMINI_MODEL` | Идентификатор модели | `gemini-1.5-pro` |
| `LLM_PLAN_MODEL` / `LLM_ANALYSIS_MODEL` | Модели для планирования и анализа | `gemini-1.5-pro` |
| `LLM_TEMPERATURE` | Температура генерации Gemini | `0.0` |
| `ALLOWED_TABLES` | Список разрешённых таблиц (через запятую) | `crm_clients,crm_people,crm_appointments,crm_appointment_services,crm_services,crm_employees` |
| `DB_*` (`DB_HOST`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_PORT`) | Подключение к PostgreSQL | см. `.env.example` |
| `QUERY_MAX_ROWS` | Лимит строк в результате | `500` |
| `QUERY_TIMEOUT_SECONDS` | Тайм-аут SQL, секунд | `30` |
| `ENABLE_CONTEXT_MEMORY` | Активировать pending-хранилище | `true` |
| `REDIS_HOST` / `REDIS_PORT` / `REDIS_DB` | Настройки Redis (если используется) | `redis:6379/0` |
| `PII_MASKING_ENABLED` | Маскирование персональных данных | `false` |
| `TELEGRAM_BOT_TOKEN` | Токен бота от BotFather | — (опционально) |

---

## REST API

### POST `/query`

Запрашивает SQL-генерацию и бизнес-ответ.

```bash
curl -X POST http://localhost:9000/query \
  -H "Content-Type: application/json" \
  -d '{
        "query": "топ сотрудников по выручке",
        "memory": {},
        "pending_state": null
      }'
```

Пример ответа (укорочено):

```json
{
  "original_query": "топ сотрудников по выручке",
  "normalized_question": "топ сотрудников по выручке",
  "rephrased_query": "топ сотрудников по выручке",
  "sql": "SELECT ... FROM crm_payments ...",
  "rows": [ { "first_name": "Мария", "total_revenue": "167000.00" } ],
  "analysis_text": "Анализ выручки...",
  "suggested_followup": [],
  "iterations_used": 1,
  "confidence": 0.82,
  "telemetry": {
    "rounds": [ { "plan_confidence": 0.82, "row_count": 8 } ],
    "total_rounds": 1
  },
  "assistant_message": "Анализ выручки...",
  "memory": { "last_query": "топ сотрудников по выручке" },
  "pending_state": null
}
```

### GET `/healthz`

Возвращает состояние подключения к БД и наличие файлов `faiss_index/*`. Статус 200 — все проверки пройдены.

---

## Telegram-бот

Запуск `python app/telegram_bot.py` активирует PTB v21 приложение.

- Команды `/start` и `/reset` — приветствие и сброс контекста.
- Любой текст → вызов `_run_pipeline`, результат форматируется `render_pipeline_reply()`.
- Сообщение `sql` возвращает последний сгенерированный SQL блоком `pre`.
- Pending-состояния (если включены) сохраняются в Redis или в памяти процесса на `CONTEXT_TTL_SECONDS` секунд.

Бот повторно использует `handle_query`, поэтому REST и Telegram-ответы идентичны.

---

## Доменные эвристики и безопасность

- **Только SELECT.** `execute_sql_query` отклоняет любые DDL/DML и ограничивает запрос одним statement.
- **Whitelist таблиц.** Используются только таблицы из `ALLOWED_TABLES`.
- **Авто-LIMIT.** Если в запросе нет `LIMIT`, он оборачивается в подзапрос с лимитом `QUERY_MAX_ROWS`.
- **Маскирование ПДн.** Поля, содержащие `phone`, `email`, `passport`, `account`, при включении опции маскируются.
- **Каноническая выручка.** Планы с запросами типа «выручка» валидацией заставляются использовать `crm_payments.amount`, исключая расхождения с `crm_appointments.paid_amount`.
- **Отказ от уточнений.** Планировщик и анализатор никогда не просят пользователя уточнить запрос — ответ формируется по имеющимся данным.

---

## Кастомизация

- **Промпты.** Отредактируйте `app/pipeline/prompts/plan_v1.txt` и `analysis_v1.txt`, чтобы изменить стиль SQL или аналитических выводов. Промпты кэшируются в памяти процесса.
- **Бизнес-правила.** Эвристику можно дополнять в `plan_query` (например, принуждать выбор определённых таблиц).
- **Предзагрузка данных.** Скрипт `scripts/employee_names.py` подгружает список активных сотрудников и вызывается при старте API.
- **Схема.** Файл `data/schema_metadata.json` описывает таблицы; он автоматически попадает в системный промпт планировщика.

---

## Разработка и отладка

- Логи пишутся в stdout. Основные теги: `[Planner]`, `[SQL]`, `[Analyzer]`, `[TG→Pipeline]` и т.д.
- Для быстрой проверки синтаксиса можно выполнить `python3 -m compileall app`.
- Сэмпловые данные находятся в `db/init/*.sql`. Их можно переиспользовать для презентаций.

---

## Лицензия

Проект предназначен для демонстрации NL→SQL ассистента. Внесите свои реквизиты и уточните лицензирование перед публикацией.
