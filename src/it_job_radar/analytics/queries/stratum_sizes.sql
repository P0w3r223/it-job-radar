-- How many offers stand behind each seniority level.
--
-- Published next to every seniority chart. Most strata in a bounded sample are small, and
-- a reader cannot judge a median without knowing whether it rests on 19 offers or 300.
SELECT
    s.seniority                AS seniority,
    COUNT(DISTINCT s.offer_id) AS offers
FROM offer_seniority s
GROUP BY seniority
ORDER BY offers DESC
