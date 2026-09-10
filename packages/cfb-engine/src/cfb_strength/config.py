import os
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader -- avoids a python-dotenv dependency for one file.
    Doesn't override variables already set in the real environment.
    """
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
_load_dotenv(PROJECT_ROOT / ".env")
DATA_DIR = Path(os.environ.get("CFB_DATA_DIR", PROJECT_ROOT / "data"))
RAW_DIR = DATA_DIR / "raw"
DB_PATH = Path(os.environ.get("CFB_DB_PATH", DATA_DIR / "cfb.sqlite3"))

CFBD_API_KEY = os.environ.get("CFBD_API_KEY")
CFBD_BASE_URL = "https://api.collegefootballdata.com"

DEFAULT_SEASONS = list(range(2000, 2024))
SEASON_TYPES = ("regular", "postseason")
