-- Materialized View: читает из Kafka Engine и батчит в основную таблицу
CREATE MATERIALIZED VIEW IF NOT EXISTS clients_transactions.transactions_mv TO clients_transactions.transactions AS
SELECT transaction_id,
    transaction_time,
    merch,
    cat_id,
    amount,
    name_1,
    name_2,
    gender,
    street,
    one_city,
    us_state,
    post_code,
    lat,
    lon,
    population_city,
    jobs,
    merchant_lat,
    merchant_lon
FROM clients_transactions.transactions_kafka;