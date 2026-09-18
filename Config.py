import os
from pathlib import Path


# Carrega o .env sem exigir dependencias externas.
env_file = Path(__file__).with_name(".env")
if env_file.exists():
	for line in env_file.read_text(encoding="utf-8").splitlines():
		line = line.strip()
		if line and not line.startswith("#") and "=" in line:
			key, value = line.split("=", 1)
			os.environ.setdefault(key.strip(), value.strip().strip('"\''))


CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
GEMINI_FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "")
REDIRECT_URI = "http://127.0.0.1:8888/callback"

PORT = 8888