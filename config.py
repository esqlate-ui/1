import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "123456789").split(",")))
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "beem_super_secret_key_2024")

PROFILE_COOLDOWN = 300  # 5 минут

INTERESTS = [
    ("🎮 Игры",        "games"),
    ("💋 Флирт",       "flirt"),
    ("🔞 18+",         "adult"),
    ("🎌 Аниме",       "anime"),
    ("💬 Общение",     "talk"),
    ("🎵 Музыка",      "music"),
    ("🎬 Кино",        "movies"),
    ("✈️ Путешествия", "travel"),
    ("📸 Фото",        "photo"),
    ("🏋️ Спорт",      "sport"),
]

INTERESTS_DISPLAY = {key: name for name, key in INTERESTS}

BAN_DURATIONS = {
    "1h":      ("1 час",    3600),
    "24h":     ("24 часа",  86400),
    "7d":      ("7 дней",   604800),
    "forever": ("Навсегда", None),
}

# ── Лимиты ────────────────────────────────────────────────────────────────────
PROFILES_LIMIT_FREE    = 2
PROFILES_LIMIT_PREMIUM = 5

# ── Premium тарифы ────────────────────────────────────────────────────────────
PREMIUM_PLANS = {
    "week": {
        "label": "🗓 Неделя",
        "days":  7,
        "stars": 75,
        "ton":   0.5,
        "desc":  "7 дней Premium",
    },
    "month": {
        "label": "📅 Месяц",
        "days":  30,
        "stars": 199,
        "ton":   1.5,
        "desc":  "30 дней Premium",
    },
    "forever": {
        "label": "♾️ Навсегда",
        "days":  None,
        "stars": 499,
        "ton":   3.5,
        "desc":  "Бессрочный Premium",
    },
}

# ── TON кошелёк ───────────────────────────────────────────────────────────────
TON_WALLET = "UQDZwUwWPTFJ58IwPQGs0BKXxLTKM_-r6A6sEN8YDfq5HSOY"
