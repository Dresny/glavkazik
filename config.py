import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    TOKEN = os.getenv("TOKEN")
    CHANNEL_ID = int(os.getenv("CHANNEL_ID", "-1001234567890"))

    ADMIN_IDS_STR = os.getenv("ADMIN_IDS", "")
    if ADMIN_IDS_STR:
        ADMIN_IDS = [int(x.strip()) for x in ADMIN_IDS_STR.split(",") if x.strip()]
    else:
        ADMIN_IDS = []

    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
    PAID_OPEN_PRICE = 75
    CARDS_PATH = "data"
    COOLDOWN_FREE = 1200
    COOLDOWN_PAID = 3600

    REFERRAL_BONUS = 750
    SUGGESTION_BONUS = 500
    NEW_USER_BONUS = 100