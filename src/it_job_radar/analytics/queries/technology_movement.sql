-- How each technology's share of the market moved, run over run.
--
-- The trap this query exists to avoid: a technology's recorded count rose on every early
-- run, and none of that was the market. Coverage went from 10% to 100% in four days, so
-- the counts were tracking our sample. Shares are the only comparable quantity here, and
-- even a share is only comparable between runs that observed a comparable slice: the fetch
-- queue takes every offer posted today plus a draw from the backlog, so a partial sample
-- leans towards recent postings and their technologies with it.
--
-- Hence `$min_coverage`. A run that observed less than that share of the live market is
-- left out of the comparison entirely, rather than plotted with a caveat under it. Runs
-- that recorded no coverage at all are out for the same reason: comparability has to be
-- established, not assumed.
--
-- One run per date — the last comparable one. Several runs share a day, and taking them
-- all would make a busy day look like a week of movement.
--
-- The series is read by name (`$series`) rather than assumed: metric names carry the
-- population they were measured over and change when it does, and a rename must show up
-- here as an empty result rather than as a silent splice of two different units.
WITH run_coverage AS (
    SELECT
        s.snapshot_id   AS snapshot_id,
        s.observed_date AS observed_date,
        MAX(CASE WHEN st.metric = 'coverage_fetched' THEN st.value END) AS analysed,
        MAX(CASE WHEN st.metric = 'frame_live' THEN st.value END)       AS listed
    FROM snapshots s
    JOIN snapshot_stats st ON st.snapshot_id = s.snapshot_id
    GROUP BY s.snapshot_id, s.observed_date
),
comparable AS (
    SELECT snapshot_id, observed_date, analysed / listed AS coverage
    FROM run_coverage
    WHERE analysed IS NOT NULL
      AND listed > 0
      AND analysed / listed >= $min_coverage
),
day_run AS (
    SELECT observed_date, MAX(snapshot_id) AS snapshot_id
    FROM comparable
    GROUP BY observed_date
)
SELECT
    m.dimension     AS technology,
    d.observed_date AS observed_date,
    m.value         AS vacancies,
    m.n             AS analysed_vacancies,
    m.value / m.n   AS share,
    c.coverage      AS coverage
FROM snapshot_dimension_metrics m
JOIN day_run d    ON d.snapshot_id = m.snapshot_id
JOIN comparable c ON c.snapshot_id = m.snapshot_id
WHERE m.metric = $series
  AND m.n > 0
ORDER BY m.dimension, d.observed_date
