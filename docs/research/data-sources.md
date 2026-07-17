# Data Sources — it-job-radar

Date: 2026-07-17
Status: accepted
Author: P0w3r223 + Claude
Related to: project A2, collector + legal/ethics

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
  the full 6,449-offer base daily.
- **No personal data (GDPR)** — store only offer attributes (title, company **name**,
  city/region, salary, work mode, seniority, technologies). The `applying` block
  (recruiter URLs, reference numbers, personal-data clauses) is dropped.
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
