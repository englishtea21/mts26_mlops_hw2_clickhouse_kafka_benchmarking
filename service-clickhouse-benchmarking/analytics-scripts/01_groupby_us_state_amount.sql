SELECT
    us_state,
    sum(amount) AS total_amount,
    avg(amount) AS avg_amount,
    count() AS transaction_count
FROM PLACEHOLDER
GROUP BY us_state
ORDER BY total_amount DESC