# HW-2: сравнение ClickHouse-схем через Kafka

Бенчмарк двух схем хранения транзакций (`slow` / `fast`) в ClickHouse:
данные льются из Kafka через Kafka Engine + Materialized View, затем
сервис бенчмаркинга гоняет аналитические SQL-запросы и строит отчёт.

## Состав сервисов (`docker-compose.yaml`)

| Сервис | Что делает |
|---|---|
| `zookeeper` / `kafka` | Брокер Kafka, топик `transactions` (3 партиции) |
| `kafka-setup` | Создаёт топик при старте |
| `kafka-ui` | Веб-UI для просмотра топика и consumer-групп (`:8080`) |
| `clickhouse` | ClickHouse, БД `clients_transactions` (`:8123` HTTP, `:9000` native) |
| `clickhouse-init` | Создаёт таблицы (`01_*`), Kafka Engine таблицы (`02_*`, по одной consumer-группе на схему: `clickhouse_consumer_slow` / `clickhouse_consumer_fast` — поэтому каждая схема вычитывает **весь** топик) и Materialized View (`03_*`) |
| `service-producer` | Читает CSV, шлёт сообщения в топик Kafka |
| `clickhouse-benchmarking` | Ждёт полного перелива данных в обе таблицы, выполняет запросы из `service-clickhouse-benchmarking/analytics-scripts/*.sql` (k повторов + warmup, порядок таблиц рандомизирован), считает среднее/медиану/p90/p95/95% CI (t-критерий) и генерирует отчёт с графиками |

## Запуск

```bash
# 1. Положить данные для продюсера (см. ниже)
# 2. Запуск всего стенда
docker compose up --build
```

Порядок соблюдается автоматически: `kafka-setup` → `service-producer`
(после готовности Kafka) и `clickhouse-init` (после готовности ClickHouse)
→ `clickhouse-benchmarking` (после завершения продюсера и init).я

```bash
docker compose down        # остановить, данные и offsets сохранить
docker compose down -v     # остановить и всё удалить (топик, таблицы, offsets)
```

> `down -v` нужен перед повторным прогоном «с нуля»: иначе consumer-группы
> продолжат с закоммиченных offset'ов, а таблицы — с уже записанными строками.

## Входные данные (для `service-producer`)

Файл должен лежать здесь (монтируется read-only в `/app/raw_data`):

```
service-producer/raw_data/train.csv
```
Это train.csv из [соревнования](https://www.kaggle.com/t/1918f3f6435300327d38d6c596f97394)
Продюсер берёт случайные 100000 строк, сортирует по `transaction_time`,
отбрасывает колонку `target` (если есть) и шлёт в топик `transactions`
(имя задаётся `KAFKA_TRANSACTIONS_TOPIC` в `.env`).

## Выходные данные (от `clickhouse-benchmarking`)

Появляются на хосте в (монтируется в `/app/analytics-results`):

```
analytics-results/
├── benchmark_report.md    # основной отчёт: схемы таблиц, статистики, сводка, графики
│                          # (в отчёте — превью первых 10 строк каждого запроса)
├── benchmark_query_*.png  # scatter-графики времён по каждой паре query × table
└── csvs/                  # ПОЛНЫЕ результаты каждого запроса (без LIMIT),
                           # по одному файлу на пару query × table
```
В этой папке представлена [демонстрация отчета](analytics-results/benchmark_report.md), без csvs.

## Схемы таблиц и запросы

Схемы таблиц (DDL обеих сравниваемых схем, Kafka Engine таблицы
и Materialized View) лежат в:

```
service-clickhouse-init/clickhouse_scripts/
├── 01_create_table_slow.sql / 01_create_table_fast.sql   # итоговые MergeTree-таблицы
├── 02_kafka_engine_slow.sql / 02_kafka_engine_fast.sql   # Kafka Engine + consumer-группы
└── 03_materialized_view_slow.sql / 03_materialized_view_fast.sql
```

Аналитические запросы, которые гоняет бенчмарк, лежат в:

```
service-clickhouse-benchmarking/analytics-scripts/*.sql   # 00_*.sql … 04_*.sql
```

В каждом файле вместо имени таблицы стоит плейсхолдер `PLACEHOLDER` —
бенчмарк подставляет туда каждую найденную таблицу (`slow`/`fast`)
и выполняет запрос k раз (плюс warmup, порядок таблиц рандомизирован).

Переменные окружения — в `.env` (порты, пользователи, имена топиков).

# Использование ИИ
ИИ использовался для генерации кода для формирования отчета сервиса service-clickhouse-benchmarking а также для написания README.md