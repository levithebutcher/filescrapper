# config.py
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Bot Information
BOT_NAME = "FileScrapper Bot"
BOT_VERSION = "2.0.0"
REPO_URL = "https://github.com/levithebutcher/filescrapper"

# Telegram Bot Token (from @BotFather)
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# Bot Owner Telegram ID (optional, for admin commands)
OWNER_ID = os.getenv("OWNER_ID", "").strip()

# Target website base URL
BASE_URL = os.getenv("BASE_URL", "https://dropmms.com").strip().rstrip("/")

# Default Category URL to monitor for auto-feed if not specified
DEFAULT_CATEGORY_URL = os.getenv("DEFAULT_CATEGORY_URL", f"{BASE_URL}/forum/2-general/").strip()

# Auto-feed background check interval in seconds (default: 900s = 15 minutes)
FEED_CHECK_INTERVAL = int(os.getenv("FEED_CHECK_INTERVAL", "900"))

# Streaming domains list
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

# Message clean title max length
MAX_TITLE_LENGTH = int(os.getenv("MAX_TITLE_LENGTH", "120"))

# Max posts to fetch per forum page (DropMMS has 24-25 posts per page)
MAX_POSTS_PER_FORUM = int(os.getenv("MAX_POSTS_PER_FORUM", "25"))

# Telegram flood wait protection delay (seconds)
POST_SEND_DELAY = float(os.getenv("POST_SEND_DELAY", "1.5"))

# HTTP Request Timeout (seconds)
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "15"))

# Proxy configuration
HTTP_PROXY = os.getenv("HTTP_PROXY", "").strip()
HTTPS_PROXY = os.getenv("HTTPS_PROXY", "").strip()
PROXIES = {}
if HTTP_PROXY:
    PROXIES["http"] = HTTP_PROXY
if HTTPS_PROXY:
    PROXIES["https"] = HTTPS_PROXY
