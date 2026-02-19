import time
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InputMediaPhoto, InputMediaVideo, InputMediaAudio
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

import database as db
from config import PROFILE_COOLDOWN, INTERESTS_DISPLAY
from keyboards import main_kb, profile_view_kb

router = Router()

GENDER_MAP = {"male": "👦 Парень", "female": "👧 Девушка", "other": "⚧ Другое"}

class ProfileFSM(StatesGroup):
    collecting = State()  # Сбор медиа/текста для анкеты

def profile_caption(user: dict, profile: dict) -> str:
    interests = [INTERESTS_DISPLAY.get(i, i) for i in (user.get("interests") or "").split(",") if i]
    return (
        f"👤 <b>{user['name']}</b>, {user['age']} лет  {GENDER_MAP.get(user.get('gender'), '')}\n"
        f"🎯 {' '.join(interests)}\n\n"
        f"📝 {profile['description']}\n\n"
        f"❤️ {profile.get('likes', 0)} лайков"
    )

async def send_profile(bot: Bot, chat_id: int, user: dict, profile: dict, show_actions: bool = True):
    """Отправляет анкету с медиафайлами"""
    media_list = db.get_profile_media(profile["id"])
    caption = profile_caption(user, profile)
    kb = profile_view_kb(profile["id"], user["user_id"], profile.get("likes", 0)) if show_actions else None

    if not media_list:
        await bot.send_message(chat_id, caption, parse_mode="HTML", reply_markup=kb)
        return

    # Одиночный медиафайл
    if len(media_list) == 1:
        m = media_list[0]
        if m["media_type"] == "photo":
            await bot.send_photo(chat_id, m["file_id"], caption=caption, parse_mode="HTML", reply_markup=kb)
        elif m["media_type"] == "video":
            await bot.send_video(chat_id, m["file_id"], caption=caption, parse_mode="HTML", reply_markup=kb)
        elif m["media_type"] == "voice":
            await bot.send_voice(chat_id, m["file_id"], caption=caption, parse_mode="HTML", reply_markup=kb)
        else:
            await bot.send_message(chat_id, caption, parse_mode="HTML", reply_markup=kb)
        return

    # Медиагруппа (фото/видео)
    photo_video = [m for m in media_list if m["media_type"] in ("photo", "video")]
    if photo_video:
        media_group = []
        for i, m in enumerate(photo_video[:10]):
            cap = caption if i == 0 else None
            if m["media_type"] == "photo":
                media_group.append(InputMediaPhoto(media=m["file_id"], caption=cap, parse_mode="HTML"))
            elif m["media_type"] == "video":
                media_group.append(InputMediaVideo(media=m["file_id"], caption=cap, parse_mode="HTML"))
        await bot.send_media_group(chat_id, media_group)

    # Голосовые отдельно
    voices = [m for m in media_list if m["media_type"] == "voice"]
    for v in voices:
        await bot.send_voice(chat_id, v["file_id"], caption="🎤 Голосовое из анкеты")

    if kb:
        await bot.send_message(chat_id, "👆 Что думаешь?", reply_markup=kb)

# ── Добавить анкету ────────────────────────────────────────────────────────────

@router.message(F.text == "➕ Добавить анкету")
async def add_profile_start(message: Message, state: FSMContext):
    user = db.get_user(message.from_user.id)
    if not user or not user.get("registered"):
        await message.answer("Сначала зарегистрируйся: /start")
        return
    if db.is_banned(message.from_user.id):
        await message.answer("🚫 Ты заблокирован.")
        return
    elapsed = time.time() - db.get_last_profile_time(message.from_user.id)
    if elapsed < PROFILE_COOLDOWN:
        rem = int(PROFILE_COOLDOWN - elapsed)
        m, s = divmod(rem, 60)
        await message.answer(f"⏳ Подожди ещё <b>{m}м {s}с</b> перед созданием новой анкеты.", parse_mode="HTML")
        return

    await state.update_data(description="", media=[])
    await state.set_state(ProfileFSM.collecting)
    await message.answer(
        "📝 <b>Создание анкеты</b>\n\n"
        "Отправь текст, фото, видео, голосовые — всё что хочешь показать в анкете.\n"
        "Можно отправить несколько сообщений.\n\n"
        "Когда закончишь — нажми кнопку ниже 👇",
        parse_mode="HTML",
        reply_markup=__import__("aiogram.types", fromlist=["ReplyKeyboardMarkup"]).ReplyKeyboardMarkup(
            keyboard=[[__import__("aiogram.types", fromlist=["KeyboardButton"]).KeyboardButton(text="✅ Опубликовать анкету")]],
            resize_keyboard=True
        )
    )

@router.message(ProfileFSM.collecting, F.text == "✅ Опубликовать анкету")
async def publish_profile(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    desc = data.get("description", "").strip()
    media = data.get("media", [])
    if not desc and not media:
        await message.answer("Анкета пустая! Добавь хотя бы текст или медиа.")
        return

    pid = db.create_profile(message.from_user.id, desc or "Загляни в мою анкету 👀")
    for m in media:
        db.add_profile_media(pid, m["file_id"], m["type"])

    await state.clear()
    profile = db.get_active_profile(message.from_user.id)
    await message.answer(
        "✅ Анкета опубликована! Другие пользователи уже могут её видеть.",
        reply_markup=main_kb(has_profile=True)
    )

@router.message(ProfileFSM.collecting)
async def collect_profile_content(message: Message, state: FSMContext):
    data = await state.get_data()
    media = data.get("media", [])
    desc = data.get("description", "")

    if message.text:
        desc = (desc + "\n" + message.text).strip()[:500]
        await state.update_data(description=desc)
        await message.answer(f"✏️ Текст добавлен ({len(desc)}/500 симв.)")
    elif message.photo:
        media.append({"file_id": message.photo[-1].file_id, "type": "photo"})
        await state.update_data(media=media)
        await message.answer(f"🖼 Фото добавлено ({len(media)} медиа)")
    elif message.video:
        media.append({"file_id": message.video.file_id, "type": "video"})
        await state.update_data(media=media)
        await message.answer(f"🎬 Видео добавлено ({len(media)} медиа)")
    elif message.voice:
        media.append({"file_id": message.voice.file_id, "type": "voice"})
        await state.update_data(media=media)
        await message.answer(f"🎤 Голосовое добавлено ({len(media)} медиа)")
    else:
        await message.answer("Поддерживается: текст, фото, видео, голосовые.")

# ── Моя анкета / Удалить ──────────────────────────────────────────────────────

@router.message(F.text == "📝 Моя анкета")
async def my_profile(message: Message, bot: Bot):
    user = db.get_user(message.from_user.id)
    profile = db.get_active_profile(message.from_user.id)
    if not profile:
        await message.answer("У тебя нет активной анкеты.", reply_markup=main_kb(False))
        return
    await message.answer("📋 <b>Твоя анкета:</b>", parse_mode="HTML")
    await send_profile(bot, message.chat.id, user, profile, show_actions=False)

@router.message(F.text == "🗑 Удалить анкету")
async def del_profile(message: Message):
    profile = db.get_active_profile(message.from_user.id)
    if not profile:
        await message.answer("У тебя нет активной анкеты.", reply_markup=main_kb(False))
        return
    db.delete_active_profile(message.from_user.id)
    await message.answer("🗑 Анкета удалена.", reply_markup=main_kb(False))

# ── Просмотр анкет ─────────────────────────────────────────────────────────────

@router.message(F.text == "👥 Анкеты")
async def browse_profiles(message: Message, bot: Bot):
    if db.is_banned(message.from_user.id):
        await message.answer("🚫 Ты заблокирован.")
        return
    user = db.get_user(message.from_user.id)
    if not user or not user.get("registered"):
        await message.answer("Сначала зарегистрируйся: /start")
        return
    interests = [i for i in (user.get("interests") or "").split(",") if i]
    profiles = db.get_matching_profiles(message.from_user.id, interests, limit=2)
    if not profiles:
        await message.answer("😔 Пока нет подходящих анкет. Попробуй позже или измени интересы в настройках!")
        return
    for p in profiles:
        p_user = db.get_user(p["user_id"])
        if not p_user:
            continue
        await send_profile(bot, message.chat.id, p_user, p, show_actions=True)

# ── Лайк ──────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("like:"))
async def like_profile_cb(callback: CallbackQuery):
    profile_id = int(callback.data.split(":")[1])
    liked = db.like_profile(profile_id, callback.from_user.id)

    # Обновить кнопку
    conn = db.get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM profiles WHERE id=%s", (profile_id,))
    cols = [d[0] for d in c.description]
    row = c.fetchone()
    conn.close()
    if row:
        p = dict(zip(cols, row))
        from keyboards import profile_view_kb
        try:
            await callback.message.edit_reply_markup(
                reply_markup=profile_view_kb(profile_id, p["user_id"], p.get("likes", 0))
            )
        except:
            pass
    await callback.answer("❤️ Лайк!" if liked else "💔 Лайк убран")
