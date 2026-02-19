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
    "1h":       ("1 час",      3600),
    "24h":      ("24 часа",    86400),
    "7d":       ("7 дней",     604800),
    "forever":  ("Навсегда",   None),
}
