#!/bin/bash

set -e

CLICKHOUSE_HOST="${CLICKHOUSE_HOST}"
CLICKHOUSE_PORT="${CLICKHOUSE_HTTP_PORT}"
CLICKHOUSE_USER="${CLICKHOUSE_USER}"
CLICKHOUSE_PASSWORD="${CLICKHOUSE_PASSWORD}"
SQL_DIR="${SQL_DIR}"

echo "Ожидание готовности ClickHouse на $CLICKHOUSE_HOST:$CLICKHOUSE_PORT..."

# Ждём пока ClickHouse станет доступен
for i in {1..30}; do
    if curl -s -f -u "$CLICKHOUSE_USER:$CLICKHOUSE_PASSWORD" "http://$CLICKHOUSE_HOST:$CLICKHOUSE_PORT/?query=SELECT%201" > /dev/null 2>&1; then
        echo "ClickHouse готов! Авторизация прошла успешно."
        break
    fi
    echo "Попытка $i/30: ClickHouse ещё не готов, ждём 2с..."
    sleep 2
done

if ! curl -s -f -u "$CLICKHOUSE_USER:$CLICKHOUSE_PASSWORD" "http://$CLICKHOUSE_HOST:$CLICKHOUSE_PORT/?query=SELECT%201" > /dev/null 2>&1; then
    echo "ОШИБКА: ClickHouse не стал доступен за 60 секунд"
    exit 1
fi

for sql_file in "$SQL_DIR"/01_create_table.sql "$SQL_DIR"/02_kafka_engine.sql "$SQL_DIR"/03_materialized_view.sql; do
    if [[ -f "$sql_file" ]]; then
        echo "Выполнение $sql_file..."
        if curl -s -f -u "$CLICKHOUSE_USER:$CLICKHOUSE_PASSWORD" \
            "http://$CLICKHOUSE_HOST:$CLICKHOUSE_PORT/" \
            --data-binary @"$sql_file"; then
            echo "Успешно: $sql_file"
        else
            echo "ОШИБКА при выполнении: $sql_file"
            exit 1
        fi
    else
        echo "Файл не найден: $sql_file"
        exit 1
    fi
done

echo "Все SQL скрипты выполнены успешно!"