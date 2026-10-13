from pathlib import Path

# Shown on the site; the site reads these from summary.meta, never from typed text.
PRODUCT_NAME = "Wispr Flow"
PRODUCT_COMPANY = "Wispr"
PLAY_APP_ID = "com.wispr.flowapp"
APPSTORE_ID = "6497229487"
# Six languages are left out for this app: on 2026-10-12 Play returned zero Wispr Flow reviews for
# ur, bn, ta, mr, ms and te, and the pinned scraper library raises on a fully empty stream.
PLAY_LANGS = (
    "en", "es", "pt", "fr", "ar", "id", "ru", "de", "ko", "it", "th", "vi", "tr", "ja", "hi",
    "nl", "pl", "sv", "da", "nb", "fi", "cs", "el", "hu", "ro", "uk", "bg", "hr", "sk", "sr",
    "iw", "fa", "fil", "zh-TW", "zh-CN", "ca",
)
PLAY_COUNTRY = "us"
# 50 storefronts: the feed caps at 500 reviews each, so breadth is the only way to add iOS volume.
APPSTORE_COUNTRIES = (
    "us", "gb", "in", "ca", "au", "de", "fr", "es", "br", "mx",
    "jp", "kr", "id", "sg", "ae", "nl", "it", "se", "ch", "ie",
    "nz", "za", "il", "pl", "at", "be", "dk", "no", "fi", "pt",
    "tr", "ph", "my", "th", "vn", "hk", "tw", "sa", "eg", "ng",
    "co", "ar", "cl", "pe", "cz", "ro", "hu", "gr", "ua", "pk",
)
# All-time run: the app has too few reviews for a 90-day window (about 3k). 600 days reaches back
# past the oldest App Store review the feed serves (May 2025); Android launched Feb 13, 2026.
WINDOW_DAYS = 600
MAX_ROWS = 200_000
SEED = 42
PAGE_SIZE = 200
PAGE_DELAY = 0.5
RETRIES = 3
HTTP_TIMEOUT = (10, 45)
DATA_DIR = Path(__file__).resolve().parents[1] / "data"
COLUMNS = (
    "review_id", "platform", "country", "store_lang", "timestamp", "date_utc", "rating",
    "title", "review_text", "app_version", "thumbs_up", "has_dev_reply",
)

ANNOTATION_MODEL = "claude-haiku-5-5"
ANNOTATION_BATCH_SIZE = 25
ANNOTATION_OUTPUT_TOKENS_PER_REVIEW = 180
ANNOTATION_PRICE_READ_DATE = "2026-10-09"
ANNOTATION_PRICING_URL = "https://platform.claude.com/docs/en/about-claude/pricing"
# USD per million tokens, used by dry runs and explicit --offline-prices runs.
ANNOTATION_ESTIMATE_PRICES = {
    "short": {"input": 0.10, "output": 0.50, "cache_write": 0.125, "cache_read": 0.01},
    "long": {"input": 0.50, "output": 2.50, "cache_write": 0.625, "cache_read": 0.05},
}
ANNOTATION_LONG_PROMPT_THRESHOLD = 100_000
