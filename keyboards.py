from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from config import INTERESTS, PREMIUM_PLANS

# ── Главное меню ──────────────────────────────────────────────────────────────

def main_kb(has_profile: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text="👥 Анкеты"), KeyboardButton(text="💬 Мои чаты")],
        [
            KeyboardButton(text="📝 Моя анкета") if has_profile else KeyboardButton(text="➕ Добавить анкету"),
            KeyboardButton(text="⚙️ Настройки"),
        ],
        [KeyboardButton(text="👑 Premium")],
    ]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)

# ── Меню в чате (постоянное reply-меню) ──────────────────────────────────────

def chat_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🚫 Заблокировать и закрыть"), KeyboardButton(text="⚠️ Пожаловаться")],
            [KeyboardButton(text="🎮 КМН"), KeyboardButton(text="🔚 Выйти из чата")],
        ],
        resize_keyboard=True
    )

def kmn_start_kb(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🎮 Начать КМН!", callback_data=f"kmn:start:{chat_id}"),
        InlineKeyboardButton(text="❌ Отмена",      callback_data="kmn:cancel_start"),
    ]])

# ── Пол ───────────────────────────────────────────────────────────────────────

def gender_kb(prefix: str = "gender") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👦 Парень", callback_data=f"{prefix}:male"),
         InlineKeyboardButton(text="👧 Девушка", callback_data=f"{prefix}:female")],
        [InlineKeyboardButton(text="⚧ Другое / Не указывать", callback_data=f"{prefix}:other")],
    ])

# ── Интересы (по 2 в ряд) ────────────────────────────────────────────────────

def interests_kb(selected: list) -> InlineKeyboardMarkup:
    rows = []
    items = list(INTERESTS)
    for i in range(0, len(items), 2):
        row = []
        for name, key in items[i:i+2]:
            check = "✅ " if key in selected else ""
            row.append(InlineKeyboardButton(text=f"{check}{name}", callback_data=f"interest:{key}"))
        rows.append(row)
    rows.append([InlineKeyboardButton(text="✔️ Готово", callback_data="interest:done")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

# ── Анкета (просмотр) ─────────────────────────────────────────────────────────

def profile_view_kb(profile_id: int, target_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💌 Написать", callback_data=f"openchat:{profile_id}:{target_id}")],
    ])

# ── Настройки ─────────────────────────────────────────────────────────────────

def settings_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Имя",   callback_data="set:name"),
         InlineKeyboardButton(text="🎂 Возраст", callback_data="set:age")],
        [InlineKeyboardButton(text="⚧ Пол",    callback_data="set:gender")],
        [InlineKeyboardButton(text="🎯 Интересы", callback_data="set:interests")],
    ])

# ── Фильтры (только для Premium) ─────────────────────────────────────────────

def filters_kb(search_gender: str, age_min: int, age_max: int,
               media_only: bool) -> InlineKeyboardMarkup:
    gender_labels = {"any": "👥 Все", "male": "👦 Парни", "female": "👧 Девушки"}
    cur_g = gender_labels.get(search_gender, "👥 Все")
    mo = "✅" if media_only else "☐"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Пол: {cur_g}", callback_data="filter:gender")],
        [InlineKeyboardButton(text=f"Возраст: {age_min}–{age_max}",
                              callback_data="filter:age")],
        [InlineKeyboardButton(text=f"{mo} Только с фото/видео",
                              callback_data="filter:media_only")],
        [InlineKeyboardButton(text="✅ Сохранить", callback_data="filter:save")],
    ])

def filter_gender_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Все",     callback_data="fgender:any"),
         InlineKeyboardButton(text="👦 Парни",   callback_data="fgender:male"),
         InlineKeyboardButton(text="👧 Девушки", callback_data="fgender:female")],
    ])

# ── Удаление анкеты (подтверждение) ──────────────────────────────────────────

def confirm_delete_profile_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Да, удалить", callback_data="delprofile:yes"),
         InlineKeyboardButton(text="❌ Отмена",       callback_data="delprofile:no")],
    ])

# ── Жалоба ────────────────────────────────────────────────────────────────────

def report_reason_kb(chat_id: int) -> InlineKeyboardMarkup:
    reasons = [
        ("🔞 Нежелательный контент", "nsfw"),
        ("💬 Спам",                   "spam"),
        ("😡 Оскорбления",            "abuse"),
        ("🤖 Бот/скам",               "scam"),
    ]
    rows = [[InlineKeyboardButton(text=r[0], callback_data=f"reportreason:{chat_id}:{r[1]}")] for r in reasons]
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_report")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

# ── Список чатов ──────────────────────────────────────────────────────────────

def my_chats_kb(chats: list, user_id: int) -> InlineKeyboardMarkup:
    rows = []
    for c in chats[:15]:
        unread = c.get("unread", 0)
        badge  = f" 🔴{unread}" if unread else ""
        rows.append([
            InlineKeyboardButton(
                text=f"💬 Чат #{c['id']}{badge}",
                callback_data=f"openchatid:{c['id']}"
            ),
            InlineKeyboardButton(text="✖️", callback_data=f"closechat:{c['id']}"),
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)

# ── Admin бан ─────────────────────────────────────────────────────────────────

def admin_ban_kb(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏰ 1 час",    callback_data=f"ban:{user_id}:1h"),
         InlineKeyboardButton(text="⏰ 24 часа",  callback_data=f"ban:{user_id}:24h")],
        [InlineKeyboardButton(text="📅 7 дней",   callback_data=f"ban:{user_id}:7d"),
         InlineKeyboardButton(text="🔒 Навсегда", callback_data=f"ban:{user_id}:forever")],
        [InlineKeyboardButton(text="✅ Разбанить", callback_data=f"unban:{user_id}")],
        [InlineKeyboardButton(text="👑 Выдать Premium", callback_data=f"adm:giveprem:{user_id}")],
    ])

# ── Premium ───────────────────────────────────────────────────────────────────

def premium_plans_kb() -> InlineKeyboardMarkup:
    rows = []
    for key, p in PREMIUM_PLANS.items():
        stars = p["stars"]
        ton   = p["ton"]
        rows.append([
            InlineKeyboardButton(
                text=f"{p['label']} — {stars}⭐ / {ton} TON",
                callback_data=f"prem:choose:{key}"
            )
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def premium_pay_kb(plan_key: str) -> InlineKeyboardMarkup:
    p = PREMIUM_PLANS[plan_key]
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"⭐ Оплатить {p['stars']} Stars",
            callback_data=f"prem:pay_stars:{plan_key}"
        )],
        [InlineKeyboardButton(
            text=f"💎 Оплатить {p['ton']} TON",
            callback_data=f"prem:pay_ton:{plan_key}"
        )],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="prem:back")],
    ])
