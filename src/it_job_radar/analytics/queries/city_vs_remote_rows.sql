-- Disclosed salaries for one city against fully remote offers.
--
-- Rows, not medians, for the same reason as salary_rows.sql: the caller attaches the
-- interval and the `n`.
--
-- Per ADVERT on the city arm, deliberately: a role advertised in eighteen cities really is
-- offered in eighteen cities, and collapsing it would erase the geography this comparison
-- exists to show. The remote arm is the opposite case and was wrong until an audit caught
-- it — all eighteen copies of one remote job land in the same bucket, which inflated that
-- arm by 28% (715 rows against 559 vacancies) and moved its median floor by 800 PLN. So the
-- two arms count differently, on purpose, and the reason is written here rather than left
-- for a reader to reverse-engineer.
--
-- The two groups overlap by construction — a Wrocław offer can also be remote — so this
-- compares two overlapping populations, not a partition. `group_name` labels which side a
-- row was counted on; a row can appear on both.
SELECT DISTINCT
    'city' AS group_name, sal.offer_id AS row_id, sal.monthly_from, sal.monthly_to
FROM offer_salaries sal
JOIN offer_locations loc ON loc.offer_id = sal.offer_id
JOIN sitemap_offers f ON f.offer_id = sal.offer_id
  AND f.last_seen = (SELECT MAX(last_seen) FROM sitemap_offers)
WHERE loc.city = $city
  AND sal.currency = $currency AND sal.kind = $kind AND sal.monthly_from IS NOT NULL

UNION ALL

SELECT DISTINCT
    'remote' AS group_name, COALESCE(o.vacancy_id, sal.offer_id) AS row_id,
    sal.monthly_from, sal.monthly_to
FROM offer_salaries sal
JOIN offer_work_modes wm ON wm.offer_id = sal.offer_id
JOIN sitemap_offers f ON f.offer_id = sal.offer_id
  AND f.last_seen = (SELECT MAX(last_seen) FROM sitemap_offers)
LEFT JOIN offers o ON o.offer_id = sal.offer_id
WHERE wm.work_mode = $work_mode
  AND sal.currency = $currency AND sal.kind = $kind AND sal.monthly_from IS NOT NULL

-- Bootstrapped by the caller, so the row order is part of the published figure.
ORDER BY group_name, row_id, monthly_from, monthly_to
