-- Query 1: Transaction count grouped by US state
SELECT
    us_state,
    max(amount) AS max_amount
FROM PLACEHOLDER
GROUP BY us_state
ORDER BY transaction_count DESC