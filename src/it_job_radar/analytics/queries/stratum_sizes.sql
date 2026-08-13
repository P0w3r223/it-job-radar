-- How many vacancies stand behind each seniority level.
--
-- Counted per VACANCY, not per advert. One employer publishes a single role once per city —
-- 18 adverts for the same Cloud Data Engineer, same technologies, same salary — so counting
-- adverts lets posting volume stand in for demand. Measured when this changed: 4354 adverts
-- were 2856 vacancies, and the ranking moved azure from third place to seventh.
-- `vacancy_id` is a salted hash of title and company; an advert without one (either field
-- missing) falls back to its own id and stands alone, which is the safe direction.
--
-- Published next to every seniority chart. Most strata in a bounded sample are small, and
-- a reader cannot judge a median without knowing whether it rests on 19 offers or 300.
SELECT
    s.seniority                AS seniority,
    COUNT(DISTINCT COALESCE(o.vacancy_id, s.offer_id)) AS offers
FROM offer_seniority s
LEFT JOIN offers o ON o.offer_id = s.offer_id
GROUP BY seniority
-- The tie-break is not cosmetic: this order reaches the page, and the guard in CI
-- compares the page byte for byte.
ORDER BY offers DESC, seniority
