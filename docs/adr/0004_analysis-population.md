# ADR 0004 — The analysed population is the live frame, not everything ever collected

Date: 2026-08-13
Status: accepted
Author: P0w3r223 + Claude
Related to: `docs/adr/0003_sampling-design.md`, `src/it_job_radar/analytics/queries/*.sql`

---

## Context

Until this decision, every published query read the whole `offers` table. Nothing joined the
population frame, so an offer analysed once stayed in every chart forever — including after
the source stopped listing it.

An audit measured the drift after two days of operation:

| | |
|---|---|
| offers analysed | 6839 |
| still listed on the observed date | 6530 |
| delisted since we fetched them | 63 |
| collected before the frame existed (2026-07-17) | 246 |

So 4.5 % of the figures described work that is no longer on offer. The share is small today
only because the project is young. Under steady daily operation the source retires several
hundred adverts a day and we hold attributes for nearly all of them, so the analysed set
becomes an archive that grows without bound against a market that does not. The page is
headed "snapshot", and its headline KPI reads "of the live market".

The same defect had already produced an impossible number elsewhere: coverage counted every
offer ever fetched over the offers listed today, and reached **101 %**.

## Decision

**Published market figures describe offers the source lists on the observed date.** Every
counting query joins `sitemap_offers` and filters on `last_seen`, and the coverage numerator
does the same.

Consequences, accepted deliberately:

- The 246 offers collected before the frame existed leave the analysis permanently. Nothing
  records whether they were still listed on any later date, so including them would mean
  asserting a liveness we never observed.
- Figures move slightly and will keep moving as adverts retire — `sql` fell from 760 mentions
  counted over the archive to 746 over the live frame at the time of the change. That is the
  intended behaviour: a technology stops counting when the offers asking for it close.
- The dated series keeps its own denominator per point, so a stored point stays readable
  against the market as it was that day.

## Alternatives considered

**Keep the archive as the population and rename the claims.** Larger `n`, complete history,
no join. Rejected because the archive answers a different question than the page asks: "what
was advertised since we started watching" is a defensible metric and is not "what the market
offers now", which is what a snapshot dated today promises.

**Two populations — live figures, archive trends.** The most correct answer and the most
expensive: one artifact carrying two denominators, with the reader obliged to track which
number came from which. Deferred rather than refused; if survival analysis (phase 7.3) needs
the archive, it will read the frame directly, where entry and exit dates already live.

## What would reopen this

A published figure that a reader can only interpret historically — median time-to-close, for
instance — would need the archive population, and this ADR would gain a second, explicitly
named set rather than being reversed.
