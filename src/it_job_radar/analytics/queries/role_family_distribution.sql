-- What kind of work the market is actually offering, optionally within one seniority.
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
    COUNT(DISTINCT o.offer_id)              AS offers
FROM offers o
LEFT JOIN offer_seniority s ON s.offer_id = o.offer_id
WHERE (CAST($seniority AS VARCHAR) IS NULL OR s.seniority = $seniority)
GROUP BY role_family
ORDER BY offers DESC, role_family
