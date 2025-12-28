# config.py

import os
from dotenv import load_dotenv

load_dotenv()

HEADLESS_BROWSER = os.getenv("HEADLESS_BROWSER", "true").lower() == "true"
APP_ENV = os.getenv("APP_ENV", "development")
