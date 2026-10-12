-- Основная таблица для хранения транзакций, быстрая DLL
CREATE TABLE IF NOT EXISTS clients_transactions.transactions_fast_for_us_state (
    transaction_id String,
    transaction_time DateTime,
    merch LowCardinality(String),
    cat_id LowCardinality(String),
    amount Float64,
    name_1 String,
    name_2 String,
    gender LowCardinality(String),
    street String,
    one_city LowCardinality(String),
    us_state LowCardinality(String),
    post_code UInt64,
    lat Float64,
    lon Float64,
    population_city UInt64,
    jobs LowCardinality(String),
    merchant_lat Float64,
    merchant_lon Float64
) ENGINE = MergeTree() PARTITION BY toYYYYMM(transaction_time)
ORDER BY (us_state, transaction_time) SETTINGS index_granularity = 8192,
    optimize_aggregation_in_order = 1;