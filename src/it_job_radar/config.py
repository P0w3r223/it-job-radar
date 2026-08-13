"""Central configuration: source, scraping etiquette, paths, normalization maps.

No I/O here — only constants. The scraping settings encode the project's ethical
guardrails: throttle between requests, sample a bounded slice rather than the whole base,
and drop personal data. (The User-Agent is a realistic browser string, not a self-ID,
because the site serves a stripped page otherwise — see docs/research/data-sources.md.)
"""

from __future__ import annotations

from pathlib import Path

# --- Paths -------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
DB_PATH = DATA_DIR / "job_offers.db"
NORMALIZATION_DIR = DATA_DIR / "normalization"
TECH_ALIASES_PATH = NORMALIZATION_DIR / "tech_aliases.yaml"
ROLE_FAMILIES_PATH = NORMALIZATION_DIR / "role_families.yaml"
CONTRACT_PATH = DATA_DIR / "contract.yaml"

# --- Source: theprotocol.it (robots.txt allows sitemap + offer pages) --------
# robots.txt publishes this index; its children list every currently open offer. Reading
# the index (rather than a hardcoded child) keeps us correct when the source re-splits it.
TP_SITEMAP_INDEX_URL = "https://theprotocol.it/sitemaps/CurrentOffers/sitemap_index.xml"
TP_OFFER_HOST = "https://theprotocol.it"

# --- Polite scraping ---------------------------------------------------------
# theprotocol serves a stripped page to non-browser agents, so we send a realistic
# browser UA to get the server-rendered data. robots.txt permits these paths; we stay
# respectful via throttling, bounded sampling, dropping personal data, and attribution.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
REQUEST_DELAY_S = 1.0  # pause between offer fetches
REQUEST_TIMEOUT_S = 25

# --- Sampling (ADR 0003) -----------------------------------------------------
# Presence comes from the sitemap frame (one request, whole population). Offer pages are
# fetched at most once per offer, bounded per run — never the whole base at once (EU
# database sui generis right). The budget is provisional until the observer measures the
# real daily inflow; see docs/plan/0001_implementation-walkthrough.md, open question 2.
DEFAULT_FETCH_BUDGET = 300
# Hard ceiling on one run's page fetches. This is the ethical guardrail, not a tuning
# knob: exceeding it is an error, because the collector must never approach the whole base.
MAX_FETCH_BUDGET = 1000
# Share of the budget spent re-fetching known offers to check whether their attributes
# really are immutable. Small on purpose: it measures an assumption, it is not a refresh.
AUDIT_QUOTA_SHARE = 0.02

# Fetch state of an offer in the population frame.
FETCH_PENDING = "pending"
FETCH_DONE = "fetched"
FETCH_FAILED = "failed"

# Cohorts differ in what they can prove: offers already listed at day 0 have an unknown
# entry date (left truncation) and must never be used for lifetime estimation.
COHORT_STOCK = "stock"  # present in the first frame we ever recorded
COHORT_FLOW = "flow"  # first appeared while we were observing

# Snapshot kinds — an observe run touches the frame only; a collect run also fetches pages.
SNAPSHOT_OBSERVE = "observe"
SNAPSHOT_COLLECT = "collect"

# --- Reporting thresholds ----------------------------------------------------
# Strata smaller than this are labelled and greyed rather than plotted as if solid.
MIN_STRATUM_N = 30
# Resamples behind every published median's confidence interval.
BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_CONFIDENCE = 0.95
# The seniority the page's headline is about, and therefore the one whose composition is
# recorded run over run rather than only for the current snapshot.
HEADLINE_SENIORITY = "junior"

# --- Dated series (phase 7.1) ------------------------------------------------
# Points below this and the chart draws no connecting line. A line between two points is a
# claim about what happened between them; with a series this short there is nothing to
# interpolate, so the points are shown and the reader is told how many there are.
MIN_SERIES_POINTS = 3
# How many technologies each run records. Deliberately wider than any chart shows: a
# technology that enters the top twelve next month needs its earlier values to draw a line
# at all, and a run that has passed cannot be measured again.
HISTORY_TECHNOLOGY_LIMIT = 30

# --- Published artifact (ADR 0002) -------------------------------------------
# The dataset lives inside the published site: it *is* the artifact the page downloads,
# so it is committed rather than generated on the reader's behalf.
PUBLISH_DIR = PROJECT_ROOT / "docs"
DATASET_DIR = PUBLISH_DIR / "data"
MANIFEST_NAME = "manifest.json"
# Tables that make up the dataset. Order is irrelevant to correctness, but keeping the
# frame and the series last groups the "what exists" and "how it moved" tables after the
# "what it contains" ones. Declared here rather than in export.py because the analytics
# engine registers the same list as views, and a constant two modules share is
# configuration — not the property of whichever one happens to write it.
DATASET_TABLES = (
    "offers",
    "offer_seniority",
    "offer_work_modes",
    "offer_locations",
    "offer_technologies",
    "offer_salaries",
    "snapshots",
    "snapshot_stats",
    "snapshot_dimension_metrics",
    "sitemap_offers",
)
# A static site must not accumulate a database by accident. Exceeding this is an error.
MAX_ARTIFACT_BYTES = 5_000_000
SOURCE_NAME = "theprotocol.it"
SOURCE_URL = "https://theprotocol.it"
ATTRIBUTION = (
    "Job data © theprotocol.it (Grupa Pracuj), collected respectfully for educational, "
    "non-commercial use."
)
# Columns that never leave this machine: with them the artifact would be a copy of the
# source's listings; without them it answers market questions and nothing else.
REDACTED_COLUMNS = ("title", "company", "offer_url")
# Kept out of the artifact for a different reason: not privacy but scope. `raw_name` is
# bookkeeping for the alias repair loop, and ADR 0002 promises the published dataset holds
# normalized attributes rather than free text from the source.
INTERNAL_COLUMNS = ("raw_name",)
# How many unresolved technology names the quality report names. Enough to act on, short
# enough to paste into the dictionary in one sitting.
UNMATCHED_IN_DETAIL = 20
# Not a secret and not stored as one. It breaks casual joins back to the source while
# keeping ids stable across snapshots so longitudinal analysis still works.
EXPORT_ID_SALT = "it-job-radar"
EXPORT_ID_LENGTH = 16

# --- Normalization -----------------------------------------------------------
# Seniority: theprotocol positionLevelIds + Polish free-text fallbacks.
# Note the Polish quirk: "regular" means mid, not entry-level.
SENIORITY_MAP = {
    "trainee": "intern", "stażysta": "intern", "praktykant": "intern", "intern": "intern",
    "junior": "junior", "młodszy": "junior", "assistant": "junior",
    "mid": "mid", "regular": "mid", "middle": "mid",
    "senior": "senior", "starszy": "senior",
    "expert": "expert", "lead": "lead", "principal": "principal", "manager": "manager",
    # "head" appears in the source data but had no mapping, so it fell through unranked
    # and sorted last in every seniority chart.
    "head": "head", "dyrektor": "head", "director": "head",
}
SENIORITY_ORDER = (
    "intern", "junior", "mid", "senior", "expert", "lead", "principal", "manager", "head",
)

# Role family: what kind of work the title describes. Rules live in ROLE_FAMILIES_PATH;
# "other" is a legitimate outcome and is reported as a quality metric, never hidden.
ROLE_FAMILY_OTHER = "other"
# What the classifier could not place: "other" is a title the rule table saw and did not
# match, "unclassified" is an offer it has not run on (the label role_family_distribution
# substitutes for NULL — the two must stay spelled the same). Neither is a kind of work,
# so neither can carry a claim about the market; both stay in every published count.
ROLE_FAMILY_UNCLASSIFIED = "unclassified"
ROLE_FAMILY_RESIDUE = (ROLE_FAMILY_OTHER, ROLE_FAMILY_UNCLASSIFIED)
# The families the page's "not development jobs" claim is measured against. Families are
# fine-grained enough that development could pass half the market while each single one
# stays under the largest non-development family, so the claim is checked against their
# sum rather than inferred from the ranking. Deliberately generous about what counts as
# development — every family here builds software — because a wide reading is the one that
# can falsify the claim, and a claim that cannot be falsified is not a finding.
DEVELOPMENT_FAMILIES = ("software", "backend", "frontend", "fullstack", "mobile", "ml")

# Work mode normalization (theprotocol detailedWorkModes codes).
WORK_MODE_MAP = {
    "remote": "remote", "home-office": "remote",
    "hybrid": "hybrid",
    "office": "office", "full-office": "office", "stationary": "office",
    "mobile": "mobile",
}
WORK_MODE_REMOTE = "remote"  # canonical remote label, referenced by analysis queries

# Salary handling. B2B is net-on-invoice, employment (UoP) is gross — kept separate.
KNOWN_CURRENCIES = ("PLN", "EUR", "USD", "GBP")
CONTRACT_B2B = "b2b"
CONTRACT_EMPLOYMENT = "employment"
CONTRACT_KINDS = (CONTRACT_B2B, CONTRACT_EMPLOYMENT)
# A monthly figure outside this band is a unit error, not a salary — the contract rejects it
# rather than letting one bad row drag a median. Both bounds are the same mistake seen from
# its two sides: a monthly amount filed as hourly lands above the ceiling, an hourly rate
# filed as monthly lands under the floor. Observed under the floor: 31.40 PLN "miesięcznie",
# which is to the grosz the statutory *hourly* minimum, and B2B architects at 140 PLN.
# The floor sits far below any lawful full-time monthly wage, so it can only catch the
# error it is aimed at.
SALARY_SANITY_MAX = 200_000
SALARY_SANITY_MIN = 1_000

# --- Value domains, referenced by data/contract.yaml via `allowed_from` ------
# Kept here so the contract and the code cannot disagree about what is valid.
WORK_MODE_VALUES = tuple(sorted(set(WORK_MODE_MAP.values())))
COHORTS = (COHORT_STOCK, COHORT_FLOW)
FETCH_STATES = (FETCH_PENDING, FETCH_DONE, FETCH_FAILED)

# Location focus for the "Wrocław vs remote" comparison.
FOCUS_CITY = "Wrocław"
