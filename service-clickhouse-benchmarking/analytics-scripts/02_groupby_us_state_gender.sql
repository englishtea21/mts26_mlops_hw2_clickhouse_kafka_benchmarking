SELECT
    us_state,
    gender,
    count() AS transaction_count,
    sum(amount) AS total_amount,
    avg(amount) AS avg_amount
FROM PLACEHOLDER
GROUP BY us_state, gender
ORDER BY us_state, total_amount DESC