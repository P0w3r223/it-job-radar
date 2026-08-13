-- How many vacancies stand behind each seniority level.
--
-- LIVE OFFERS ONLY. The page calls itself a snapshot and the KPI reads "of the live
-- market", so the population is what the source lists on the observed date, not everything
-- ever collected. Without the join the analysed set becomes an archive that only grows:
-- two days in, 309 of 6839 analysed offers were already off the market, and at a few
-- hundred departures a day that share climbs indefinitely. Offers collected before the
-- frame existed have no row here and are excluded for the same reason — nothing records
-- whether they were still listed.
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
JOIN sitemap_offers f ON f.offer_id = s.offer_id
  AND f.last_seen = (SELECT MAX(last_seen) FROM sitemap_offers)
GROUP BY seniority
-- The tie-break is not cosmetic: this order reaches the page, and the guard in CI
-- compares the page byte for byte.
ORDER BY offers DESC, seniority
