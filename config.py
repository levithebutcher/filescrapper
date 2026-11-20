# config.py
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Bot Information
BOT_NAME = "FileScrapper Bot"
BOT_VERSION = "1.2.0"
REPO_URL = "https://github.com/levithebutcher/filescrapper"

# Telegram Bot Token (BotFather se prapt karein)
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# Optional Bot Owner Telegram ID
OWNER_ID = os.getenv("OWNER_ID", "").strip()

# Streaming domains ki list (sirf inhi links ko extract karenge)
_custom_domains = os.getenv("STREAMING_DOMAINS")
if _custom_domains:
    STREAMING_DOMAINS = [d.strip().lower() for d in _custom_domains.split(",") if d.strip()]
else:
    STREAMING_DOMAINS = [
        "vidara.to",
        "streamtape.com",
        "streamfiles.net",
        "lplaygo.com",
        "doodstream.com",
        "dood.",
        "streamwish",
        "filelions",
        "dropload",
        "mixdrop",
        "streamruby",
    ]

# Target website ka base URL
BASE_URL = os.getenv("BASE_URL", "https://dropmms.com").strip()

# Message clean rakhne ke liye title ki max length
MAX_TITLE_LENGTH = int(os.getenv("MAX_TITLE_LENGTH", "120"))

# Ek forum page se maximum kitne posts nikaalne hain (Telegram spam/rate-limit se bachne ke liye)
MAX_POSTS_PER_FORUM = int(os.getenv("MAX_POSTS_PER_FORUM", "15"))

# Telegram flood wait se bachne ke liye har post ke beech delay (seconds)
POST_SEND_DELAY = float(os.getenv("POST_SEND_DELAY", "1.5"))

# HTTP Request Timeout (seconds)
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "15"))

# Optional Proxy support (agar ISP ya network par site blocked ho to proxy use karein)
HTTP_PROXY = os.getenv("HTTP_PROXY", "").strip()
HTTPS_PROXY = os.getenv("HTTPS_PROXY", "").strip()
PROXIES = {}
if HTTP_PROXY:
    PROXIES["http"] = HTTP_PROXY
if HTTPS_PROXY:
    PROXIES["https"] = HTTPS_PROXY
