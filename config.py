import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is not set in the .env file! Please add it.")

ALLOWED_USER_IDS = [7747086163, 1994789266, 6605229065]

PAGE_SIZE = 10
SEARCH_PAGE_SIZE = 10


# --- Proxy ---
PROXY_URL = os.getenv("PROXY_URL", "socks5://127.0.0.1:10808")

# --- Limits ---
MAX_FILE_SIZE_MB = 50  # تلگرام برای ربات‌ها ۵۰ MB محدودیت داره
ARTIST_CACHE_FILE = "/home/daytona/.sc_artist_cache.json"
DOWNLOAD_HISTORY_DB = "/home/daytona/.sc_download_history.db"
LOG_FILE = "bot.log"
LOG_MAX_BYTES = 10 * 1024 * 1024  # ۱۰ MB
LOG_BACKUP_COUNT = 5
