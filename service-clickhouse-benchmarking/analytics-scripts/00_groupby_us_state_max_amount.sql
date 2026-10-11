SELECT
    us_state,
    max(amount) AS max_amount
FROM PLACEHOLDER
GROUP BY us_state
ORDER BY max_amount DESC