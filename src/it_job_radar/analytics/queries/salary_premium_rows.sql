-- One row per live vacancy that discloses a monthly floor under `$kind`, with everything a
-- premium model is allowed to control for.
--
-- Rows, not an aggregate, for the reason `salary_rows` gives: the filter is the part that
-- must be defined exactly once, and the model that consumes these rows needs the
-- observations rather than a summary of them.
--
-- The floor, not the midpoint. A range's upper bound is disclosed less often and is the
-- more aspirational of the two numbers; modelling the floor keeps every row on the same
-- definition instead of silently mixing "floor" and "middle of a range".
--
-- Per VACANCY: one role published in eighteen cities is one salary offer, and the median of
-- its rows is taken because an employer can file several ranges against one job.
--
-- `kind` is B2B or employment and never pooled — they are different amounts of money for
-- the same work.
--
-- Seniority, work mode and technologies come back as pipe-joined lists rather than as
-- extra rows: a vacancy can carry several of each, and expanding them here would multiply
-- the salary across its own attributes. The model expands them into indicators.
--
-- City is deliberately absent. Under this project's unit of analysis a job is not in a
-- city — one vacancy is advertised across eighteen of them — so a city control would
-- describe the advert's distribution rather than the job's location.
WITH salaries AS (
    SELECT
        COALESCE(o.vacancy_id, s.offer_id) AS vacancy,
        MEDIAN(s.monthly_from)             AS monthly_floor
    FROM offer_salaries s
    JOIN offers o ON o.offer_id = s.offer_id
    JOIN sitemap_offers f ON f.offer_id = s.offer_id
      AND f.last_seen = (SELECT MAX(last_seen) FROM sitemap_offers)
    WHERE s.kind = $kind
      AND s.currency = $currency
      AND s.monthly_from IS NOT NULL
    GROUP BY vacancy
),
attributes AS (
    SELECT
        COALESCE(o.vacancy_id, o.offer_id)          AS vacancy,
        STRING_AGG(DISTINCT sn.seniority, '|')      AS seniority,
        STRING_AGG(DISTINCT w.work_mode, '|')       AS work_modes,
        STRING_AGG(DISTINCT CASE WHEN NOT $required_only OR t.required = 1
                                 THEN t.technology END, '|') AS technologies
    FROM offers o
    LEFT JOIN offer_seniority sn   ON sn.offer_id = o.offer_id
    LEFT JOIN offer_work_modes w   ON w.offer_id = o.offer_id
    LEFT JOIN offer_technologies t ON t.offer_id = o.offer_id
    GROUP BY vacancy
)
SELECT
    s.vacancy       AS vacancy,
    s.monthly_floor AS monthly_floor,
    a.seniority     AS seniority,
    a.work_modes    AS work_modes,
    a.technologies  AS technologies
FROM salaries s
JOIN attributes a ON a.vacancy = s.vacancy
ORDER BY s.vacancy
