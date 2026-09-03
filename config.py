import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "whisper-large-v3-turbo")
LLM_MODEL = os.environ.get("LLM_MODEL", "openai/gpt-oss-20b")
ANALYZE_MODEL = os.environ.get("ANALYZE_MODEL", "openai/gpt-oss-120b")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / os.environ.get("DB_PATH", "expense_tracker.db")

TG = f"https://api.telegram.org/bot{BOT_TOKEN}"
