-- How the analysed sample accumulated, run by run.
--
-- The claim this figure exists to check: a bounded, polite collector reaches a useful share
-- of the market by coming back, not by fetching harder. Every run appears — an `observe`
-- costs a handful of requests and moves the frame only, a `collect` also spends its bounded
-- page budget — so the flat steps are as much a part of the evidence as the rises.
--
-- The series is ordinal, not a time axis. Runs sit minutes or days apart, and spacing them
-- evenly along a date axis would suggest a rate nobody measured.
--
-- `offers_listed` is what the source published that day: the denominator of coverage, and
-- the ceiling the accumulation is climbing towards. A run recording one number but not the
-- other cannot be plotted and is left out rather than drawn against a missing base.
SELECT
    s.snapshot_id   AS snapshot_id,
    s.observed_date AS observed_date,
    s.kind          AS kind,
    MAX(CASE WHEN st.metric = 'coverage_fetched' THEN st.value END) AS offers_analysed,
    MAX(CASE WHEN st.metric = 'frame_live' THEN st.value END)       AS offers_listed
FROM snapshots s
JOIN snapshot_stats st ON st.snapshot_id = s.snapshot_id
GROUP BY s.snapshot_id, s.observed_date, s.kind
HAVING MAX(CASE WHEN st.metric = 'coverage_fetched' THEN st.value END) IS NOT NULL
   AND MAX(CASE WHEN st.metric = 'frame_live' THEN st.value END) IS NOT NULL
-- Run order, which is the only order that makes an accumulation monotonic.
ORDER BY s.snapshot_id
