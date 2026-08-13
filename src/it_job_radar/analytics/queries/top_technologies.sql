-- Most in-demand technologies.
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
WHERE (NOT $required_only OR t.required = 1)
  AND (CAST($seniority AS VARCHAR) IS NULL OR s.seniority = $seniority)
  AND (CAST($role_family AS VARCHAR) IS NULL OR o.role_family = $role_family)
GROUP BY technology
ORDER BY offers DESC, technology
LIMIT $limit
