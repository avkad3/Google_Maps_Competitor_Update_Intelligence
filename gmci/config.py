"""Runtime configuration, read from environment variables (and an optional .env file).

Credentials are only ever read from the environment; nothing here is written back to disk.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(BASE_DIR / ".env")


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def env_flag(name: str, default: bool = False) -> bool:
    value = env(name, "1" if default else "0").lower()
    return value in {"1", "true", "yes", "on"}


DATA_DIR = Path(env("GMCI_DATA_DIR", str(BASE_DIR / "data"))).resolve()
DB_PATH = DATA_DIR / "gmci.db"
MEDIA_DIR = DATA_DIR / "media"
SCREENSHOT_DIR = DATA_DIR / "screenshots"
CHROME_PROFILE = env("GMCI_CHROME_PROFILE", str(DATA_DIR / "chrome-profile"))
HEADLESS = env_flag("GMCI_HEADLESS", True)
SEED_DEMO = env_flag("GMCI_SEED_DEMO", True)
SECRET_KEY = env("SECRET_KEY", "dev-only-not-secret")

for _d in (DATA_DIR, MEDIA_DIR, SCREENSHOT_DIR):
    _d.mkdir(parents=True, exist_ok=True)
