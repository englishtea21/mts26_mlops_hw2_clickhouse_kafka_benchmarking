-- Query 5: Monthly transactions by US state
SELECT
    toYYYYMM(transaction_time) AS year_month,
    us_state,
    count() AS transaction_count,
    sum(amount) AS total_amount
FROM PLACEHOLDER
GROUP BY year_month, us_state
ORDER BY year_month DESC, transaction_count DESC