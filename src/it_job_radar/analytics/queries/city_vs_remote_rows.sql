-- Disclosed salaries for one city against fully remote offers.
--
-- Rows, not medians, for the same reason as salary_rows.sql: the caller attaches the
-- interval and the `n`.
--
-- Per ADVERT, deliberately, while every other published figure counts vacancies. This
-- question is about where work is offered, and a role advertised in eighteen cities really
-- is offered in eighteen cities; collapsing it to one would erase the geography the chart
-- exists to show.
--
-- The two groups overlap by construction — a Wrocław offer can also be remote — so this
-- compares two overlapping populations, not a partition. `group_name` labels which side a
-- row was counted on; a row can appear on both.
SELECT
    'city' AS group_name, sal.monthly_from, sal.monthly_to
FROM offer_salaries sal
JOIN offer_locations loc ON loc.offer_id = sal.offer_id
WHERE loc.city = $city
  AND sal.currency = $currency AND sal.kind = $kind AND sal.monthly_from IS NOT NULL

UNION ALL

SELECT
    'remote' AS group_name, sal.monthly_from, sal.monthly_to
FROM offer_salaries sal
JOIN offer_work_modes wm ON wm.offer_id = sal.offer_id
WHERE wm.work_mode = $work_mode
  AND sal.currency = $currency AND sal.kind = $kind AND sal.monthly_from IS NOT NULL

-- Bootstrapped by the caller, so the row order is part of the published figure.
ORDER BY group_name, monthly_from, monthly_to
