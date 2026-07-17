"""Central configuration: source, scraping etiquette, paths, normalization maps.

No I/O here — only constants. The scraping settings encode the project's ethical
guardrails (identify ourselves, throttle, sample a bounded slice rather than the whole
base); see docs/research/data-sources.md.
"""

from __future__ import annotations

from pathlib import Path

# --- Paths -------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
DB_PATH = DATA_DIR / "job_offers.db"
FIGURES_DIR = PROJECT_ROOT / "reports" / "figures"
NORMALIZATION_DIR = DATA_DIR / "normalization"
TECH_ALIASES_PATH = NORMALIZATION_DIR / "tech_aliases.yaml"

# --- Source: theprotocol.it (robots.txt allows sitemap + offer pages) --------
TP_SITEMAP_URL = (
    "https://static.theprotocol.it/sitemaps/CurrentOffers/SiteMapJobOffers1.xml"
)
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
# Bounded sample per run — never extract the whole base (EU database sui generis right).
DEFAULT_SAMPLE_SIZE = 300

# --- Normalization -----------------------------------------------------------
# Seniority: theprotocol positionLevelIds + Polish free-text fallbacks.
# Note the Polish quirk: "regular" means mid, not entry-level.
SENIORITY_MAP = {
    "trainee": "intern", "stażysta": "intern", "praktykant": "intern", "intern": "intern",
    "junior": "junior", "młodszy": "junior", "assistant": "junior",
    "mid": "mid", "regular": "mid", "middle": "mid",
    "senior": "senior", "starszy": "senior",
    "expert": "expert", "lead": "lead", "principal": "principal", "manager": "manager",
}
SENIORITY_ORDER = ("intern", "junior", "mid", "senior", "expert", "lead", "principal", "manager")

# Work mode normalization (theprotocol detailedWorkModes codes).
WORK_MODE_MAP = {
    "remote": "remote", "home-office": "remote",
    "hybrid": "hybrid",
    "office": "office", "full-office": "office", "stationary": "office",
    "mobile": "mobile",
}

# Salary handling. B2B is net-on-invoice, employment (UoP) is gross — kept separate.
KNOWN_CURRENCIES = ("PLN", "EUR", "USD", "GBP")
CONTRACT_B2B = "b2b"
CONTRACT_EMPLOYMENT = "employment"

# Location focus for the "Wrocław vs remote" comparison.
FOCUS_CITY = "Wrocław"
