# ADR 0002 — What the published data artifact may contain

Date: 2026-08-11
Status: accepted
Author: P0w3r223
Related to: `docs/adr/0001_browser-side-analytics-stack.md`, `docs/research/data-sources.md`

---

## Context

ADR 0001 ships a dataset to the browser. That turns an internal SQLite file into a
**publicly downloadable artifact**, which is a materially different act from publishing
three aggregate charts.

The project's collection ethics (README, `docs/research/data-sources.md`) rest on three
commitments: a bounded sample rather than the whole base (EU database *sui generis*
right), no personal data, and attribution. A published Parquet mirroring the offer rows
would honour the first two while quietly undermining the reasoning behind them — a file
containing titles, employer names and offer URLs is a partial copy of the source's
listings, redistributable and usable as a substitute for visiting the site.

The competing pressure is analytical: the more the artifact is stripped, the less the
reader can drill into.

## Decision

Publish a **derived analytical artifact, deliberately non-substitutable for the source**.

Included: normalized structured attributes only — seniority, work mode, city and region,
technologies with their required flag, contract kind, currency, time unit, monthly
salary bounds, role family, `first_seen` / `last_seen`, and snapshot metadata.

Excluded from the published files: `title`, `company`, `offer_url`, and any free text.
`offer_id` is replaced by a salted hash, stable across snapshots so longitudinal joins still
work.

**Amended 2026-08-13 — the hash is pseudonymisation, not anonymisation.** This section used
to say the hash was "not resolvable back to a listing", which an audit showed is false as
written: the salt is committed to this repository, `offer_id` is the GUID in the offer URL,
and the source publishes every live GUID in one sitemap request. Re-linking the published
rows to their listings therefore costs one request and a few thousand hashes. `vacancy_id`
is sharper still, because it hashes exactly the two fields — title and company — that
redaction exists to withhold, and the sitemap's URL slugs carry the title.

The property the artifact actually has is the one the code always claimed: casual joins back
to the source are broken, and the artifact is useless as a job-board substitute. A secret
HMAC key would make the stronger claim true, at the cost of an artifact nobody could
reproduce from a clone — the reproducibility this project treats as a feature. Given that
the underlying listings are public and no personal data is published, the claim was
corrected rather than the mechanism. A published artifact asserting a property it does not
have is the defect; the mechanism was never the problem.

The salt lives in the repository, not in a secret store: the goal is to remove the
artifact's usefulness as a job-board substitute and to break casual joins back to the
source, not to defend against a determined adversary. Claiming otherwise would be
security theatre.

The full, unredacted data stays local in `data/job_offers.db`, which is git-ignored.
Every published file carries attribution in `manifest.json` and in the page footer.

## Alternatives considered

**Publish the full offer rows.** Maximum analytical value; the reader could search by
employer or open the original posting. Rejected: it is redistribution of the source's
listings under a different roof, and it makes the "bounded sample" commitment
performative — the bound stops mattering once the sample is republished in full.

**Publish nothing; keep pre-rendered aggregates only.** Safest, and the status quo.
Rejected because it forecloses the drill-down that ADR 0001 exists to enable, and the
risk it avoids is already addressed by redaction.

**Publish company names but drop titles and URLs.** Rejected: employer name is the field
that makes the artifact commercially interesting to re-use, and it adds little to the
market-level questions this project asks.

**Aggregate-only export (counts per cell, no offer-level rows).** Considered seriously.
Rejected because cross-cutting filters would require pre-computing the full dimension
product, which is the exact limitation ADR 0001 rejects — and offer-level rows stripped
of identifying fields carry no more re-use risk than the cell counts do.

## Consequences

- The artifact answers *market* questions (what is in demand, what it pays, where, on
  what contract) and cannot answer *listing* questions (who is hiring, where to apply).
  This is the intended boundary, and it is stated on the page.
- Redaction is enforced in code, in `export.py`, and covered by a test asserting the
  excluded columns are absent from every published file — not left to reviewer vigilance.
- Longitudinal analysis survives redaction via the stable salted hash.
- P4 `pl-jobs-lora`, which needs offer prose, must consume the **local** database
  directly rather than the published artifact. Recorded here so the constraint is not
  rediscovered later.
- `docs/research/data-sources.md` should gain a short section pointing at this ADR, so
  the ethics reasoning stays in one reachable place.
