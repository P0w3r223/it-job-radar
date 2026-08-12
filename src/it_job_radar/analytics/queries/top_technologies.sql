-- Most in-demand technologies.
--
-- Counts distinct offers rather than mentions, so one offer never counts twice.
-- `required_only` (the default) excludes nice-to-haves: pooling them with must-haves
-- overweights optional skills and blurs the question "what does the market demand".
--
-- Optional filters: seniority, role family. Both matter more than they look — "top
-- technologies for juniors" without a role filter mixes developer roles with IT support
-- and reports a helpdesk profile.
SELECT
    t.technology                AS technology,
    COUNT(DISTINCT t.offer_id)  AS offers
FROM offer_technologies t
LEFT JOIN offer_seniority s ON s.offer_id = t.offer_id
LEFT JOIN offers o          ON o.offer_id = t.offer_id
WHERE (NOT $required_only OR t.required = 1)
  AND (CAST($seniority AS VARCHAR) IS NULL OR s.seniority = $seniority)
  AND (CAST($role_family AS VARCHAR) IS NULL OR o.role_family = $role_family)
GROUP BY technology
ORDER BY offers DESC, technology
LIMIT $limit
