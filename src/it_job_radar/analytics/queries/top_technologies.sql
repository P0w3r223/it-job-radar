-- Most in-demand technologies.
--
-- LIVE OFFERS ONLY. The page calls itself a snapshot and the KPI reads "of the live
-- market", so the population is what the source lists on the observed date, not everything
-- ever collected. Without the join the analysed set becomes an archive that only grows:
-- two days in, 309 of 6839 analysed offers were already off the market, and at a few
-- hundred departures a day that share climbs indefinitely. Offers collected before the
-- frame existed have no row here and are excluded for the same reason — nothing records
-- whether they were still listed.
--
-- Counts distinct vacancies rather than mentions, so neither one advert nor one
-- employer's per-city reposting counts twice.
--
-- Counted per VACANCY, not per advert. One employer publishes a single role once per city —
-- 18 adverts for the same Cloud Data Engineer, same technologies, same salary — so counting
-- adverts lets posting volume stand in for demand. Measured when this changed: 4354 adverts
-- were 2856 vacancies, and the ranking moved azure from third place to seventh.
-- `vacancy_id` is a salted hash of title and company; an advert without one (either field
-- missing) falls back to its own id and stands alone, which is the safe direction.
-- `required_only` (the default) excludes nice-to-haves: pooling them with must-haves
-- overweights optional skills and blurs the question "what does the market demand".
--
-- Optional filters: seniority, role family. Both matter more than they look — "top
-- technologies for juniors" without a role filter mixes developer roles with IT support
-- and reports a helpdesk profile.
SELECT
    t.technology                AS technology,
    COUNT(DISTINCT COALESCE(o.vacancy_id, t.offer_id)) AS offers
FROM offer_technologies t
LEFT JOIN offer_seniority s ON s.offer_id = t.offer_id
LEFT JOIN offers o          ON o.offer_id = t.offer_id
JOIN sitemap_offers f ON f.offer_id = t.offer_id
  AND f.last_seen = (SELECT MAX(last_seen) FROM sitemap_offers)
WHERE (NOT $required_only OR t.required = 1)
  AND (CAST($seniority AS VARCHAR) IS NULL OR s.seniority = $seniority)
  AND (CAST($role_family AS VARCHAR) IS NULL OR o.role_family = $role_family)
GROUP BY technology
ORDER BY offers DESC, technology
LIMIT $limit
