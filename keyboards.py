from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from config import INTERESTS, INTERESTS_DISPLAY

def main_kb(has_profile: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text="👥 Анкеты"), KeyboardButton(text="💬 Мои чаты")],
        [KeyboardButton(text="➕ Добавить анкету") if not has_profile else KeyboardButton(text="📝 Моя анкета"),
         KeyboardButton(text="🗑 Удалить анкету") if has_profile else KeyboardButton(text="⚙️ Настройки")],
    ]
    if has_profile:
        rows.append([KeyboardButton(text="⚙️ Настройки")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)

def gender_kb(prefix: str = "gender") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👦 Парень", callback_data=f"{prefix}:male"),
         InlineKeyboardButton(text="👧 Девушка", callback_data=f"{prefix}:female")],
        [InlineKeyboardButton(text="⚧ Другое / Не указывать", callback_data=f"{prefix}:other")],
    ])

def interests_kb(selected: list) -> InlineKeyboardMarkup:
    rows = []
    for name, key in INTERESTS:
        check = "✅ " if key in selected else ""
        rows.append([InlineKeyboardButton(text=f"{check}{name}", callback_data=f"interest:{key}")])
    rows.append([InlineKeyboardButton(text="✔️ Готово", callback_data="interest:done")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def profile_view_kb(profile_id: int, target_id: int, likes: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"❤️ {likes}", callback_data=f"like:{profile_id}"),
         InlineKeyboardButton(text="💌 Написать", callback_data=f"openchat:{profile_id}:{target_id}")],
    ])

def chat_kb(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Ответить", callback_data=f"reply:{chat_id}"),
         InlineKeyboardButton(text="🚫 Заблокировать", callback_data=f"block:{chat_id}"),
         InlineKeyboardButton(text="⚠️ Пожаловаться", callback_data=f"report:{chat_id}")],
    ])

def report_reason_kb(chat_id: int) -> InlineKeyboardMarkup:
    reasons = [
        ("🔞 Нежелательный контент", "nsfw"),
        ("💬 Спам", "spam"),
        ("😡 Оскорбления", "abuse"),
        ("🤖 Бот/скам", "scam"),
    ]
    rows = [[InlineKeyboardButton(text=r[0], callback_data=f"reportreason:{chat_id}:{r[1]}")] for r in reasons]
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def settings_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Имя", callback_data="set:name"),
         InlineKeyboardButton(text="🎂 Возраст", callback_data="set:age")],
        [InlineKeyboardButton(text="⚧ Пол", callback_data="set:gender")],
        [InlineKeyboardButton(text="🎯 Интересы", callback_data="set:interests")],
    ])

def admin_ban_kb(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏰ 1 час", callback_data=f"ban:{user_id}:1h"),
         InlineKeyboardButton(text="⏰ 24 часа", callback_data=f"ban:{user_id}:24h")],
        [InlineKeyboardButton(text="📅 7 дней", callback_data=f"ban:{user_id}:7d"),
         InlineKeyboardButton(text="🔒 Навсегда", callback_data=f"ban:{user_id}:forever")],
        [InlineKeyboardButton(text="✅ Разбанить", callback_data=f"unban:{user_id}")],
    ])

def my_chats_kb(chats: list, user_id: int) -> InlineKeyboardMarkup:
    rows = []
    for c in chats[:15]:
        role = "📨" if c["sender_id"] == user_id else "📬"
        rows.append([InlineKeyboardButton(
            text=f"{role} Чат #{c['id']}",
            callback_data=f"openchatid:{c['id']}"
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows)
