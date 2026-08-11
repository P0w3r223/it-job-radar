-- Individual disclosed salaries, filtered to one currency and one contract kind.
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
SELECT
    sal.offer_id      AS offer_id,
    s.seniority       AS seniority,
    o.role_family     AS role_family,
    sal.monthly_from  AS monthly_from,
    sal.monthly_to    AS monthly_to
FROM offer_salaries sal
JOIN offer_seniority s ON s.offer_id = sal.offer_id
LEFT JOIN offers o     ON o.offer_id = sal.offer_id
WHERE sal.currency = $currency
  AND sal.kind = $kind
  AND sal.monthly_from IS NOT NULL
