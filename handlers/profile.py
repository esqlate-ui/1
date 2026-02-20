import time
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InputMediaPhoto, InputMediaVideo
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

import database as db
from config import PROFILE_COOLDOWN, INTERESTS_DISPLAY, PROFILES_LIMIT_FREE, PROFILES_LIMIT_PREMIUM
from keyboards import main_kb, profile_view_kb, confirm_delete_profile_kb, filters_kb, filter_gender_kb

router = Router()

GENDER_MAP = {"male": "👦 Парень", "female": "👧 Девушка", "other": "⚧ Другое"}

class ProfileFSM(StatesGroup):
    collecting = State()

class FilterFSM(StatesGroup):
    age_range = State()

def profile_caption(user: dict, profile: dict) -> str:
    is_prem = db.is_premium(user["user_id"])
    badge   = "👑 " if is_prem else ""
    interests = [INTERESTS_DISPLAY.get(i, i) for i in (user.get("interests") or "").split(",") if i]
    return (
        f"{badge}<b>{user['name']}</b>, {user['age']} лет  {GENDER_MAP.get(user.get('gender'), '')}\n"
        f"🎯 {' '.join(interests)}\n\n"
        f"📝 {profile['description']}"
    )

async def send_profile(bot: Bot, chat_id: int, user: dict, profile: dict,
                       show_actions: bool = True):
    media_list = db.get_profile_media(profile["id"])
    caption    = profile_caption(user, profile)
    kb = profile_view_kb(profile["id"], user["user_id"]) if show_actions else None

    if not media_list:
        await bot.send_message(chat_id, caption, parse_mode="HTML", reply_markup=kb)
        return

    if len(media_list) == 1:
        m = media_list[0]
        if m["media_type"] == "photo":
            await bot.send_photo(chat_id, m["file_id"], caption=caption,
                                 parse_mode="HTML", reply_markup=kb)
        elif m["media_type"] == "video":
            await bot.send_video(chat_id, m["file_id"], caption=caption,
                                 parse_mode="HTML", reply_markup=kb)
        elif m["media_type"] == "voice":
            await bot.send_voice(chat_id, m["file_id"])
            await bot.send_message(chat_id, caption, parse_mode="HTML", reply_markup=kb)
        else:
            await bot.send_message(chat_id, caption, parse_mode="HTML", reply_markup=kb)
        return

    # Медиагруппа — кнопки к последнему сообщению
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

    voices = [m for m in media_list if m["media_type"] == "voice"]
    for v in voices:
        await bot.send_voice(chat_id, v["file_id"])

    if kb:
        await bot.send_message(chat_id, "👆 Написать:", reply_markup=kb)

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

    # Кулдаун только для бесплатных
    if not db.is_premium(message.from_user.id):
        elapsed = time.time() - db.get_last_profile_time(message.from_user.id)
        if elapsed < PROFILE_COOLDOWN:
            rem  = int(PROFILE_COOLDOWN - elapsed)
            m, s = divmod(rem, 60)
            await message.answer(
                f"⏳ Подожди ещё <b>{m}м {s}с</b> перед созданием новой анкеты.\n"
                f"<i>👑 Premium снимает это ограничение!</i>",
                parse_mode="HTML"
            )
            return

    await state.update_data(description="", media=[])
    await state.set_state(ProfileFSM.collecting)

    is_prem = db.is_premium(message.from_user.id)
    media_hint = (
        "Можно отправить фото, видео, голосовые."
        if is_prem else
        "Бесплатно: только текст и голосовые. Фото и видео — с 👑 Premium."
    )
    await message.answer(
        f"📝 <b>Создание анкеты</b>\n\n"
        f"Отправь описание и медиа.\n{media_hint}\n\n"
        f"Когда закончишь — нажми кнопку ниже 👇",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="✅ Опубликовать анкету")]],
            resize_keyboard=True
        )
    )

@router.message(ProfileFSM.collecting, F.text == "✅ Опубликовать анкету")
async def publish_profile(message: Message, state: FSMContext, bot: Bot):
    data  = await state.get_data()
    desc  = data.get("description", "").strip()
    media = data.get("media", [])
    if not desc and not media:
        await message.answer("Анкета пустая! Добавь хотя бы текст или голосовое.")
        return

    pid = db.create_profile(message.from_user.id, desc or "Загляни в мою анкету 👀")
    for m in media:
        db.add_profile_media(pid, m["file_id"], m["type"])

    await state.clear()
    await message.answer(
        "✅ Анкета опубликована! Другие пользователи уже могут её видеть.",
        reply_markup=main_kb(has_profile=True)
    )

@router.message(ProfileFSM.collecting)
async def collect_profile_content(message: Message, state: FSMContext):
    data  = await state.get_data()
    media = data.get("media", [])
    desc  = data.get("description", "")
    is_prem = db.is_premium(message.from_user.id)

    if message.text:
        desc = (desc + "\n" + message.text).strip()[:500]
        await state.update_data(description=desc)
        await message.answer(f"✏️ Текст добавлен ({len(desc)}/500 симв.)")
    elif message.voice:
        media.append({"file_id": message.voice.file_id, "type": "voice"})
        await state.update_data(media=media)
        await message.answer(f"🎤 Голосовое добавлено ({len(media)} медиа)")
    elif message.photo:
        if not is_prem:
            await message.answer("📸 Фото только для 👑 Premium. Голосовые и текст — бесплатно!")
        else:
            media.append({"file_id": message.photo[-1].file_id, "type": "photo"})
            await state.update_data(media=media)
            await message.answer(f"🖼 Фото добавлено ({len(media)} медиа)")
    elif message.video:
        if not is_prem:
            await message.answer("🎬 Видео только для 👑 Premium.")
        else:
            media.append({"file_id": message.video.file_id, "type": "video"})
            await state.update_data(media=media)
            await message.answer(f"🎬 Видео добавлено ({len(media)} медиа)")
    else:
        await message.answer("Поддерживается: текст, голосовые" + (", фото, видео." if is_prem else ". Фото/видео — с Premium."))

# ── Моя анкета / Удалить ──────────────────────────────────────────────────────

@router.message(F.text == "📝 Моя анкета")
async def my_profile(message: Message, bot: Bot):
    user    = db.get_user(message.from_user.id)
    profile = db.get_active_profile(message.from_user.id)
    if not profile:
        await message.answer("У тебя нет активной анкеты.", reply_markup=main_kb(False))
        return
    await message.answer("📋 <b>Твоя анкета:</b>", parse_mode="HTML")
    await send_profile(bot, message.chat.id, user, profile, show_actions=False)
    # Показываем кнопку удаления
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    await message.answer(
        "Хочешь удалить анкету?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🗑 Удалить анкету", callback_data="delprofile:ask")]
        ])
    )

@router.callback_query(F.data == "delprofile:ask")
async def del_profile_ask(callback: CallbackQuery):
    await callback.message.edit_text(
        "Уверен? Анкету придётся создавать заново.",
        reply_markup=confirm_delete_profile_kb()
    )
    await callback.answer()

@router.callback_query(F.data == "delprofile:yes")
async def del_profile_confirm(callback: CallbackQuery):
    db.delete_active_profile(callback.from_user.id)
    await callback.message.edit_text("🗑 Анкета удалена.")
    await callback.message.answer("Главное меню:", reply_markup=main_kb(False))
    await callback.answer()

@router.callback_query(F.data == "delprofile:no")
async def del_profile_cancel(callback: CallbackQuery):
    await callback.message.edit_text("Отменено.")
    await callback.answer()

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

    is_prem    = db.is_premium(message.from_user.id)
    limit      = PROFILES_LIMIT_PREMIUM if is_prem else PROFILES_LIMIT_FREE
    interests  = [i for i in (user.get("interests") or "").split(",") if i]

    # Фильтры — только для премиума
    sg         = user.get("search_gender", "any") if is_prem else "any"
    age_min    = user.get("search_age_min", 0) if is_prem else 0
    age_max    = user.get("search_age_max", 99) if is_prem else 99
    media_only = bool(user.get("search_media_only", 0)) if is_prem else False

    profiles = db.get_matching_profiles(
        message.from_user.id, interests, limit=limit,
        search_gender=sg, age_min=age_min, age_max=age_max,
        media_only=media_only, viewer_is_premium=is_prem
    )
    if not profiles:
        await message.answer("😔 Пока нет подходящих анкет. Попробуй позже или измени интересы!")
        return

    for p in profiles:
        p_user = db.get_user(p["user_id"])
        if not p_user:
            continue
        await send_profile(bot, message.chat.id, p_user, p, show_actions=True)

    # Кнопка фильтров для премиума после показа анкет
    if is_prem:
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        await message.answer(
            "🔍 Настроить фильтры поиска:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⚙️ Фильтры", callback_data="open_filters")]
            ])
        )
    if is_prem:
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        await message.answer(
            "🔍 Настроить фильтры поиска:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⚙️ Фильтры", callback_data="open_filters")]
            ])
        )

# ── Фильтры (Premium) ─────────────────────────────────────────────────────────

@router.callback_query(F.data == "open_filters")
async def open_filters(callback: CallbackQuery):
    if not db.is_premium(callback.from_user.id):
        await callback.answer("🔒 Фильтры доступны только с 👑 Premium", show_alert=True)
        return
    user = db.get_user(callback.from_user.id)
    await callback.message.edit_text(
        "🔍 <b>Фильтры поиска</b>\n\nНастрой кого хочешь видеть:",
        parse_mode="HTML",
        reply_markup=filters_kb(
            user.get("search_gender", "any"),
            user.get("search_age_min", 0),
            user.get("search_age_max", 99),
            bool(user.get("search_media_only", 0))
        )
    )
    await callback.answer()

@router.callback_query(F.data == "filter:gender")
async def filter_gender(callback: CallbackQuery):
    await callback.message.edit_text(
        "Кого ищешь?",
        reply_markup=filter_gender_kb()
    )
    await callback.answer()

@router.callback_query(F.data.startswith("fgender:"))
async def set_filter_gender(callback: CallbackQuery):
    val  = callback.data.split(":")[1]
    user = db.get_user(callback.from_user.id)
    db.upsert_user(callback.from_user.id, search_gender=val)
    await callback.message.edit_text(
        "🔍 <b>Фильтры поиска</b>\n\nНастрой кого хочешь видеть:",
        parse_mode="HTML",
        reply_markup=filters_kb(
            val,
            user.get("search_age_min", 0),
            user.get("search_age_max", 99),
            bool(user.get("search_media_only", 0))
        )
    )
    await callback.answer("✅ Сохранено")

@router.callback_query(F.data == "filter:age")
async def filter_age_prompt(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "Введи диапазон возраста через дефис.\nПример: <b>18-30</b>",
        parse_mode="HTML"
    )
    await state.set_state(FilterFSM.age_range)
    await callback.answer()

@router.message(FilterFSM.age_range)
async def filter_age_input(message: Message, state: FSMContext):
    try:
        parts = message.text.strip().split("-")
        age_min = int(parts[0].strip())
        age_max = int(parts[1].strip())
        assert 13 <= age_min <= age_max <= 99
    except:
        await message.answer("Неверный формат. Пример: 18-30")
        return
    db.upsert_user(message.from_user.id, search_age_min=age_min, search_age_max=age_max)
    await state.clear()
    user = db.get_user(message.from_user.id)
    await message.answer(
        f"✅ Возраст: {age_min}–{age_max}\n\nФильтры обновлены!",
        reply_markup=main_kb(bool(db.get_active_profile(message.from_user.id)))
    )

@router.callback_query(F.data == "filter:media_only")
async def filter_media_only(callback: CallbackQuery):
    user     = db.get_user(callback.from_user.id)
    cur      = bool(user.get("search_media_only", 0))
    new_val  = 0 if cur else 1
    db.upsert_user(callback.from_user.id, search_media_only=new_val)
    user = db.get_user(callback.from_user.id)
    await callback.message.edit_reply_markup(
        reply_markup=filters_kb(
            user.get("search_gender", "any"),
            user.get("search_age_min", 0),
            user.get("search_age_max", 99),
            bool(new_val)
        )
    )
    await callback.answer("✅")

@router.callback_query(F.data == "filter:save")
async def filter_save(callback: CallbackQuery):
    await callback.message.edit_text("✅ Фильтры сохранены!")
    await callback.answer()
