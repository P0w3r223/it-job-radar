-- How the market splits between remote, hybrid and office.
--
-- An offer can carry several work modes (hybrid and remote are often both listed), so the
-- shares deliberately sum to more than the offer count. Presenting this as a pie chart
-- would therefore be wrong; it is a bar chart of "offers mentioning this mode".
SELECT
    work_mode                 AS work_mode,
    COUNT(DISTINCT offer_id)  AS offers
FROM offer_work_modes
GROUP BY work_mode
ORDER BY offers DESC, work_mode
