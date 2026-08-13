-- How the market splits between remote, hybrid and office.
--
-- Counted per VACANCY, not per advert. One employer publishes a single role once per city —
-- 18 adverts for the same Cloud Data Engineer, same technologies, same salary — so counting
-- adverts lets posting volume stand in for demand. Measured when this changed: 4354 adverts
-- were 2856 vacancies, and the ranking moved azure from third place to seventh.
-- `vacancy_id` is a salted hash of title and company; an advert without one (either field
-- missing) falls back to its own id and stands alone, which is the safe direction.
--
-- An offer can carry several work modes (hybrid and remote are often both listed), so the
-- shares deliberately sum to more than the offer count. Presenting this as a pie chart
-- would therefore be wrong; it is a bar chart of "offers mentioning this mode".
SELECT
    w.work_mode               AS work_mode,
    COUNT(DISTINCT COALESCE(o.vacancy_id, w.offer_id)) AS offers
FROM offer_work_modes w
LEFT JOIN offers o ON o.offer_id = w.offer_id
GROUP BY w.work_mode
ORDER BY offers DESC, w.work_mode
