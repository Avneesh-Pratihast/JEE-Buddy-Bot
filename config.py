"""
JEE Buddy Telegram Bot — Configuration
All secrets come from environment variables. Copy .env.example → .env and fill in your values.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file from the project root
load_dotenv(Path(__file__).parent / ".env")

# ── API Keys ────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")

# Support multiple Gemini API keys (comma-separated or single)
raw_keys = os.getenv("GEMINI_API_KEYS", GEMINI_API_KEY)
GEMINI_API_KEYS: list[str] = [k.strip() for k in raw_keys.split(",") if k.strip()]
if not GEMINI_API_KEYS and GEMINI_API_KEY:
    GEMINI_API_KEYS = [GEMINI_API_KEY]
if not GEMINI_API_KEY and GEMINI_API_KEYS:
    GEMINI_API_KEY = GEMINI_API_KEYS[0]

# ── User ────────────────────────────────────────────────────────────────────
# Your Telegram numeric chat ID (send /start to @userinfobot to find it)
AVNEESH_CHAT_ID: int = int(os.getenv("AVNEESH_CHAT_ID", "0"))

# ── Paths ───────────────────────────────────────────────────────────────────
OBSIDIAN_VAULT = Path(os.getenv(
    "OBSIDIAN_VAULT_PATH",
    r"C:\Users\HP\Documents\Avneesh\Avneexh_Jee_Prep",
))
DATA_DIR = Path(__file__).parent / "data"
CHAPTER_TRACKER = Path(os.getenv(
    "CHAPTER_TRACKER_PATH",
    r"C:\Users\HP\.gemini\config\skills\jee-study-commander\resources\chapter_tracker.json",
))

# ── Gemini Model ────────────────────────────────────────────────────────────
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")

# ── Schedule Times (24h format, IST) ────────────────────────────────────────
MORNING_PLAN_HOUR, MORNING_PLAN_MIN = 6, 30        # 6:30 AM
POST_COACHING_HOUR, POST_COACHING_MIN = 15, 0       # 3:00 PM
REVISION_ALERT_HOUR, REVISION_ALERT_MIN = 19, 0     # 7:00 PM
NIGHT_LOG_HOUR, NIGHT_LOG_MIN = 22, 30               # 10:30 PM

# ── Coaching Days (0 = Monday … 6 = Sunday) ─────────────────────────────────
COACHING_DAYS: list[int] = [0, 1, 2, 3, 4, 5]  # Mon–Sat; Sunday is self-study

# ── Weekly hour targets ─────────────────────────────────────────────────────
WEEKLY_TARGETS = {
    "Physics": 14,
    "Chemistry": 10,
    "Mathematics": 12,
}

# ── Validation ──────────────────────────────────────────────────────────────
def validate() -> list[str]:
    """Return a list of missing-but-required config values."""
    missing = []
    if not TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not GEMINI_API_KEY and not GEMINI_API_KEYS:
        missing.append("GEMINI_API_KEY / GEMINI_API_KEYS")
    # Chat ID 0 is allowed for initial setup (get ID from /start)
    return missing

