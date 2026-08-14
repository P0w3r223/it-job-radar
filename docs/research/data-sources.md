# Data Sources — it-job-radar

Date: 2026-07-17
Status: accepted
Author: P0w3r223
Related to: project A2, collector + legal/ethics

---

**What this research became.** Three decisions carry it forward and supersede the
collection sketch below wherever the two disagree:

- [ADR 0003 — Sampling design](../adr/0003_sampling-design.md). The sitemap turned out to
  contain the offer id, so presence is a free census and only *attributes* are sampled.
  The child sitemap named at the bottom of this document is no longer hardcoded — the
  collector discovers children from `sitemap_index.xml`, because how many there are is the
  source's business, not ours.
- [ADR 0002 — Published artifact policy](../adr/0002_published-artifact-policy.md). The
  legal reasoning here (EU database *sui generis* right, GDPR art. 14) is what shaped
  what may be *published*: derived analytical data, redacted so it cannot substitute for
  the source.
- [ADR 0001 — Browser-side analytics stack](../adr/0001_browser-side-analytics-stack.md).
  Why the published artifact is Parquet queried in the reader's browser.

---

Synthesis of the research + a live probe of the sites (2026-07-17). The decision was
driven as much by **legality/ToS** as by data richness: for a public portfolio project
the source must clearly permit machine access.

## Decision summary

| Source | Verdict | Why |
|--------|---------|-----|
| **theprotocol.it** (Grupa Pracuj) | ✅ **primary** | `robots.txt` disallows only `/_next/` and **publishes an offers sitemap** — a clear invitation to index. Rich data in `__NEXT_DATA__` (title, employer, location, seniority, work mode, contract types + salary, technologies). |
| pracujwit.pl RSS (`/rss/all/`) | backup | Deliberately published feed — safest, but poorer (usually no salary). |
| No Fluff Jobs | ❌ rejected | `robots.txt` **disallows `/api/` and `/posting/`** — exactly the endpoints needed. Scraping them would defy the owner's stated will (verified live, contradicting an earlier research claim). |
| justjoin.it | ❌ rejected | Public API shut down (~2023); `robots.txt` disallows `/api/`. |

## Legal / ethical guardrails (baked into the collector)

- **Respect robots.txt** — only fetch what theprotocol allows (sitemap + offer pages).
- **Fragmentary, not the whole base** — the EU *sui generis* database right protects
  extraction of a "substantial part". We sample a bounded number of offers per run, not
  the full base daily.

  **Corrected 2026-08-13.** That sentence described the intent and not the code: the budget
  bounded one invocation and nothing summed the invocations, so seven runs on 2026-08-13
  fetched **6037 offer pages against a 6530-offer base** — the whole base in a day, which is
  exactly what this paragraph promises never happens. The runs were the one-off backfill that
  took coverage from 10 % to 100 %, and each stayed inside the per-run ceiling, but the
  aggregate is what the rule is about. `MAX_DAILY_FETCH` now sums the day's recorded runs
  before a queue is built and trims or refuses the budget, so the promise is enforced rather
  than intended. Recorded here rather than quietly fixed, because a research note claiming a
  bound the collector did not have is the kind of thing this document exists to prevent.
- **No personal data (GDPR)** — store only offer attributes (title, company **name**,
  city/region, salary, work mode, seniority, technologies). The `applying` block
  (recruiter URLs, reference numbers, personal-data clauses) is dropped. Caveat: for a
  sole proprietorship a company name may be a person's name — a residual risk we
  knowingly accept for this educational snapshot.
- **Low rate + caching** — delays between requests, dedup on offer id.
- **Attribution + educational purpose** stated in the README.

## theprotocol.it structure (verified in `__NEXT_DATA__`)

`props.pageProps.offer` — key fields:

| Field | Path |
|-------|------|
| Title | `attributes.title.value` |
| Employer | `attributes.employer.name` |
| Location | `attributes.workplaces[].city` / `.region` |
| Seniority | `attributes.employment.positionLevelIds` (e.g. `junior`/`mid`/`senior`) |
| Work mode | `attributes.employment.detailedWorkModes[].code` (`remote`/`hybrid`/`stationary`) |
| Contracts + salary | `attributes.employment.typesOfContracts[]` (`name`, `salary` — may be `null`) |
| Technologies | `technologies.expected[].name` / `technologies.optional[].name` |

- Offers list: sitemap `https://static.theprotocol.it/sitemaps/CurrentOffers/SiteMapJobOffers1.xml`
  (offer URLs `https://theprotocol.it/szczegoly/praca/...,oferta,{id}`).
- Salary is per contract type; **B2B is net-on-invoice, UoP is gross** — never average
  them together without conversion. Currencies seen: PLN (+ EUR/USD/GBP for remote).

## Technology / seniority normalization

- **Technologies:** canonical dictionary `canonical -> [aliases]`, seeded from GitHub
  Linguist (languages) + Stack Overflow tag synonyms (frameworks/tools), e.g.
  `ReactJS`/`React.js`/`react` → `react`. Multi-stage match: exact → fuzzy (RapidFuzz).
- **Seniority (PL):** `młodszy`→junior, `starszy`→senior, `stażysta`/`praktykant`→intern,
  and note the Polish quirk **`regular` = mid**. theprotocol already gives a structured
  `positionLevelIds`, so free-text parsing is mostly a fallback.

## Sources

- theprotocol robots + sitemap: https://theprotocol.it/robots.txt · https://static.theprotocol.it/sitemaps/CurrentOffers/SiteMapJobOffers1.xml
- No Fluff Jobs robots (disallows /api/): https://nofluffjobs.com/robots.txt
- GitHub Linguist languages.yml · Stack Overflow tag synonyms (Data Explorer)
- EU database right (Dir. 96/9/EC), Ryanair v. PR Aviation (ToS enforceability), GDPR art. 14
