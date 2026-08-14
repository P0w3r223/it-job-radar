-- Which technologies are asked for together, beyond what their popularity explains.
--
-- The raw pair count answers a question nobody asked: the most frequent pair is always the
-- two most common technologies, so the ranking would just restate the demand chart twice.
-- What is worth publishing is the *lift* — how much more often two technologies share a
-- vacancy than they would if employers picked them independently. Lift 1 is chance; lift 6
-- means six times as often as chance, which is a stack, a certification track or a platform
-- rather than a coincidence.
--
-- Counted per VACANCY, like every other counting metric here: one role published in
-- eighteen cities is one job asking for that pair, not eighteen. The DISTINCT in `live`
-- collapses the per-city copies before anything is counted.
--
-- LIVE OFFERS ONLY, for the reason `top_technologies` states: the page is a snapshot of the
-- market, not of the archive.
--
-- `$min_pair_n` is the floor a pair has to clear before its lift is publishable. Lift is
-- unstable exactly where the data is thin — two technologies sharing four vacancies can
-- score higher than any real stack — so a rare pair is dropped rather than plotted as the
-- strongest finding on the page.
WITH live AS (
    SELECT DISTINCT
        COALESCE(o.vacancy_id, t.offer_id) AS vacancy,
        t.technology                       AS technology
    FROM offer_technologies t
    LEFT JOIN offers o ON o.offer_id = t.offer_id
    JOIN sitemap_offers f ON f.offer_id = t.offer_id
      AND f.last_seen = (SELECT MAX(last_seen) FROM sitemap_offers)
    WHERE (NOT $required_only OR t.required = 1)
),
totals AS (
    SELECT technology, COUNT(*) AS vacancies FROM live GROUP BY technology
),
analysed AS (
    SELECT COUNT(DISTINCT vacancy) AS vacancies FROM live
),
-- `b.technology > a.technology` does two jobs: it drops the self-pair and it keeps each
-- unordered pair once, so "python + sql" and "sql + python" cannot both be published.
pairs AS (
    SELECT a.technology AS technology_a, b.technology AS technology_b, COUNT(*) AS vacancies
    FROM live a
    JOIN live b ON b.vacancy = a.vacancy AND b.technology > a.technology
    GROUP BY a.technology, b.technology
)
SELECT
    p.technology_a AS technology_a,
    p.technology_b AS technology_b,
    p.vacancies    AS vacancies,
    ta.vacancies   AS vacancies_a,
    tb.vacancies   AS vacancies_b,
    n.vacancies    AS analysed_vacancies,
    (p.vacancies * 1.0 * n.vacancies) / (ta.vacancies * tb.vacancies) AS lift
FROM pairs p
JOIN totals ta ON ta.technology = p.technology_a
JOIN totals tb ON tb.technology = p.technology_b
CROSS JOIN analysed n
WHERE p.vacancies >= $min_pair_n
ORDER BY lift DESC, p.vacancies DESC, p.technology_a, p.technology_b
LIMIT $limit
