-- Основная таблица для хранения транзакций
CREATE TABLE IF NOT EXISTS clients_transactions.transactions (
    transaction_id String,
    transaction_time DateTime,
    merch String,
    cat_id String,
    amount Float64,
    name_1 String,
    name_2 String,
    gender String,
    street String,
    one_city String,
    us_state String,
    post_code UInt64,
    lat Float64,
    lon Float64,
    population_city UInt64,
    jobs String,
    merchant_lat Float64,
    merchant_lon Float64
) ENGINE = MergeTree() PARTITION BY toYYYYMMDD(transaction_time)
ORDER BY (transaction_time, transaction_id, cat_id) SETTINGS index_granularity = 8192;