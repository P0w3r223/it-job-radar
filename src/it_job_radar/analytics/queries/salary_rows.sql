-- Individual disclosed salaries, filtered to one currency and one contract kind.
--
-- LIVE OFFERS ONLY. The page calls itself a snapshot and the KPI reads "of the live
-- market", so the population is what the source lists on the observed date, not everything
-- ever collected. Without the join the analysed set becomes an archive that only grows:
-- two days in, 309 of 6839 analysed offers were already off the market, and at a few
-- hundred departures a day that share climbs indefinitely. Offers collected before the
-- frame existed have no row here and are excluded for the same reason — nothing records
-- whether they were still listed.
--
-- Rows, not medians. The filter is the part that must be defined once; the aggregation is
-- a median either way, and returning rows lets the caller attach a confidence interval and
-- an honest `n` instead of publishing a bare number.
--
-- B2B (net on invoice) and employment (gross) are NEVER pooled: they are different
-- amounts of money for the same work, so the contract kind is a required parameter rather
-- than an optional filter. Currency is likewise fixed, because rates change and converting
-- would bake a date into the figure.
--
-- An offer listing several seniority levels contributes to each of them — an accepted
-- modelling choice for a market overview, not an oversight.
--
-- One row per VACANCY, not per advert. The same role published once per city repeats its
-- salary in every copy, so counting adverts would weight a median by how widely an employer
-- advertises rather than by what the market pays. DISTINCT over the vacancy and the figures
-- keeps a vacancy that genuinely states two different ranges as two rows.
SELECT DISTINCT
    COALESCE(o.vacancy_id, sal.offer_id) AS offer_id,
    s.seniority       AS seniority,
    o.role_family     AS role_family,
    sal.monthly_from  AS monthly_from,
    sal.monthly_to    AS monthly_to
FROM offer_salaries sal
JOIN offer_seniority s ON s.offer_id = sal.offer_id
LEFT JOIN offers o     ON o.offer_id = sal.offer_id
JOIN sitemap_offers f ON f.offer_id = sal.offer_id
  AND f.last_seen = (SELECT MAX(last_seen) FROM sitemap_offers)
WHERE sal.currency = $currency
  AND sal.kind = $kind
  AND sal.monthly_from IS NOT NULL
-- The caller bootstraps these rows, and a resampler draws in the order it is given, so the
-- published interval depends on this ordering. SQL promises none unless it is stated.
ORDER BY seniority, offer_id, monthly_from, monthly_to
