-- What kind of work the market is actually offering, optionally within one seniority.
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
-- This is the query behind the site's headline: filtered to juniors it shows that IT
-- support, not development, is the largest junior category — which is why an unfiltered
-- "top technologies for juniors" reports active directory and microsoft office.
--
-- "other" is included rather than hidden. Its share is published as a quality metric: a
-- rising "other" means data/normalization/role_families.yaml needs work, and dropping it
-- would quietly inflate every other family.
SELECT
    COALESCE(o.role_family, 'unclassified') AS role_family,
    COUNT(DISTINCT COALESCE(o.vacancy_id, o.offer_id)) AS offers
FROM offers o
LEFT JOIN offer_seniority s ON s.offer_id = o.offer_id
JOIN sitemap_offers f ON f.offer_id = o.offer_id
  AND f.last_seen = (SELECT MAX(last_seen) FROM sitemap_offers)
WHERE (CAST($seniority AS VARCHAR) IS NULL OR s.seniority = $seniority)
GROUP BY role_family
ORDER BY offers DESC, role_family
