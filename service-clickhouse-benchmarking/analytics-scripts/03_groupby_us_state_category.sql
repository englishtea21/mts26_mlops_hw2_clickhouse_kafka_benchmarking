SELECT
    us_state,
    cat_id,
    count() AS transaction_count,
    sum(amount) AS total_amount
FROM PLACEHOLDER
GROUP BY us_state, cat_id
ORDER BY us_state, transaction_count DESC