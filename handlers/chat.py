from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramForbiddenError

import database as db
from keyboards import chat_menu_kb, main_kb, my_chats_kb, report_reason_kb

router = Router()

class ChatFSM(StatesGroup):
    active = State()

# ── Открыть чат по анкете ─────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("openchat:"))
async def open_chat(callback: CallbackQuery, state: FSMContext, bot: Bot):
    _, profile_id, target_id = callback.data.split(":")
    profile_id, target_id = int(profile_id), int(target_id)
    sender_id = callback.from_user.id

    if sender_id == target_id:
        await callback.answer("Это твоя анкета!", show_alert=True)
        return
    if db.is_blocked(target_id, sender_id):
        await callback.answer("Ты заблокирован этим пользователем.", show_alert=True)
        return

    profile = db.get_active_profile(target_id)
    if not profile or profile["id"] != profile_id:
        await callback.answer("Анкета уже неактивна.", show_alert=True)
        return

    chat_id = db.create_chat(profile_id, sender_id, target_id)
    await state.update_data(active_chat=chat_id, chat_partner=target_id)
    await state.set_state(ChatFSM.active)

    await callback.message.answer(
        "💬 <b>Чат открыт!</b>\n\n"
        "Собеседник не знает кто ты — общение анонимное.\n"
        "Можно отправлять текст, фото, видео, голосовые, кружки, стикеры, гифки.\n\n"
        "<i>Используй кнопки внизу чтобы выйти, пожаловаться или заблокировать.</i>",
        parse_mode="HTML",
        reply_markup=chat_menu_kb()
    )
    await callback.answer()

    # Уведомление получателю — показываем данные ОТПРАВИТЕЛЯ
    sender_user   = db.get_user(sender_id)
    sender_prem   = db.is_premium(sender_id)
    badge         = "👑 " if sender_prem else ""
    sender_name   = sender_user["name"] if sender_user else "Кто-то"
    sender_age    = f", {sender_user['age']} лет" if sender_user else ""
    gender_map    = {"male": "👦 Парень", "female": "👧 Девушка", "other": "⚧"}
    sender_gender = gender_map.get(sender_user.get("gender", ""), "") if sender_user else ""

    try:
        await bot.send_message(
            target_id,
            f"📬 {badge}<b>Тебе написали!</b>\n\n"
            f"👤 {sender_name}{sender_age} {sender_gender}\n\n"
            f"Зайди в <b>«💬 Мои чаты»</b> чтобы ответить.",
            parse_mode="HTML"
        )
    except (TelegramForbiddenError, Exception):
        pass

# ── Открыть чат из списка ─────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("openchatid:"))
async def open_chat_by_id(callback: CallbackQuery, state: FSMContext):
    chat_id = int(callback.data.split(":")[1])
    chat    = db.get_chat(chat_id)
    if not chat or callback.from_user.id not in (chat["sender_id"], chat["target_id"]):
        await callback.answer("Нет доступа", show_alert=True)
        return
    if chat.get("closed"):
        await callback.answer("Этот чат закрыт.", show_alert=True)
        return

    partner = chat["sender_id"] if callback.from_user.id == chat["target_id"] else chat["target_id"]
    await state.update_data(active_chat=chat_id, chat_partner=partner)
    await state.set_state(ChatFSM.active)

    # Отмечаем сообщения прочитанными
    db.mark_messages_read(chat_id, callback.from_user.id)

    # Показываем историю (последние 10)
    messages = db.get_chat_messages(chat_id, limit=20)
    if messages:
        await callback.message.answer(f"💬 <b>Чат #{chat_id} — последние сообщения:</b>", parse_mode="HTML")
        for m in messages[-10:]:
            who = "Ты" if m["sender_id"] == callback.from_user.id else "Собеседник"
            if m["msg_type"] == "text":
                await callback.message.answer(f"<b>{who}:</b> {m['content']}", parse_mode="HTML")

    await callback.message.answer(
        "Чат активен. Пиши!",
        reply_markup=chat_menu_kb()
    )
    await callback.answer()

# ── Закрыть чат навсегда ──────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("closechat:"))
async def close_chat_forever(callback: CallbackQuery, state: FSMContext):
    chat_id = int(callback.data.split(":")[1])
    chat    = db.get_chat(chat_id)
    if not chat or callback.from_user.id not in (chat["sender_id"], chat["target_id"]):
        await callback.answer("Нет доступа", show_alert=True)
        return

    # Закрываем чат и блокируем собеседника
    db.close_chat(chat_id)
    partner = chat["sender_id"] if callback.from_user.id == chat["target_id"] else chat["target_id"]
    db.block_user(callback.from_user.id, partner)

    # Если был в активном чате — выходим
    data = await state.get_data()
    if data.get("active_chat") == chat_id:
        await state.clear()

    await callback.answer("Чат закрыт навсегда.", show_alert=True)

    # Обновляем список чатов
    chats = db.get_user_chats(callback.from_user.id)
    if chats:
        try:
            await callback.message.edit_reply_markup(
                reply_markup=my_chats_kb(chats, callback.from_user.id)
            )
        except:
            pass
    else:
        try:
            await callback.message.edit_text("У тебя пока нет открытых чатов.")
        except:
            pass

# ── Мои чаты ──────────────────────────────────────────────────────────────────

@router.message(F.text == "💬 Мои чаты")
async def my_chats(message: Message):
    chats = db.get_user_chats(message.from_user.id)
    if not chats:
        await message.answer("У тебя пока нет активных чатов.")
        return
    await message.answer(
        "💬 <b>Твои чаты:</b>\n<i>🔴 — непрочитанные сообщения | ✖️ — закрыть навсегда</i>",
        parse_mode="HTML",
        reply_markup=my_chats_kb(chats, message.from_user.id)
    )

# ── Заблокировать и закрыть ───────────────────────────────────────────────────

@router.message(ChatFSM.active, F.text == "🚫 Заблокировать и закрыть")
async def block_and_close(message: Message, state: FSMContext):
    data       = await state.get_data()
    chat_id    = data.get("active_chat")
    partner_id = data.get("chat_partner")
    if chat_id:
        db.close_chat(chat_id)
    if partner_id:
        db.block_user(message.from_user.id, partner_id)
    await state.clear()
    profile = db.get_active_profile(message.from_user.id)
    await message.answer(
        "🚫 Пользователь заблокирован, чат закрыт навсегда.",
        reply_markup=main_kb(bool(profile))
    )

# ── Жалоба ────────────────────────────────────────────────────────────────────

@router.message(ChatFSM.active, F.text == "⚠️ Пожаловаться")
async def report_from_menu(message: Message, state: FSMContext):
    data    = await state.get_data()
    chat_id = data.get("active_chat")
    if not chat_id:
        await message.answer("Нет активного чата.")
        return
    await message.answer(
        "⚠️ Выбери причину жалобы:",
        reply_markup=report_reason_kb(chat_id)
    )

# ── КМН — кнопка в меню чата ─────────────────────────────────────────────────

@router.message(ChatFSM.active, F.text == "🎮 КМН")
async def kmn_button(message: Message, state: FSMContext):
    data    = await state.get_data()
    chat_id = data.get("active_chat")
    if not chat_id:
        await message.answer("Нет активного чата.")
        return

    from keyboards import kmn_start_kb
    await message.answer(
        "🎮 <b>Камень-Ножницы-Бумага со ставкой!</b>\n\n"
        "Как это работает:\n"
        "1️⃣ Ты загружаешь ставку (фото/видео/голосовое)\n"
        "2️⃣ Соперник принимает вызов и тоже загружает ставку\n"
        "3️⃣ Играете до 3 побед — проигравший автоматом отдаёт свою ставку\n\n"
        "Готов?",
        parse_mode="HTML",
        reply_markup=kmn_start_kb(chat_id)
    )

@router.callback_query(F.data == "kmn:cancel_start")
async def kmn_cancel_start(callback: CallbackQuery):
    await callback.message.edit_text("❌ Отменено.")
    await callback.answer()

# ── Выйти из чата (тоже выше relay) ──────────────────────────────────────────

@router.message(ChatFSM.active, F.text == "🔚 Выйти из чата")
async def exit_chat_active(message: Message, state: FSMContext):
    await state.clear()
    profile = db.get_active_profile(message.from_user.id)
    await message.answer("👋 Вышел из чата.", reply_markup=main_kb(bool(profile)))

# ── Пересылка сообщений ───────────────────────────────────────────────────────

@router.message(ChatFSM.active)
async def relay(message: Message, state: FSMContext, bot: Bot):
    data       = await state.get_data()
    chat_id    = data.get("active_chat")
    partner_id = data.get("chat_partner")
    if not chat_id or not partner_id:
        await state.clear()
        return

    chat = db.get_chat(chat_id)
    if chat and chat.get("closed"):
        await state.clear()
        profile = db.get_active_profile(message.from_user.id)
        await message.answer("Этот чат был закрыт.", reply_markup=main_kb(bool(profile)))
        return

    if db.is_blocked(partner_id, message.from_user.id):
        await message.answer("🚫 Собеседник заблокировал тебя.")
        await state.clear()
        return

    sender_id = message.from_user.id

    try:
        if message.text:
            db.add_message(chat_id, sender_id, message.text, "text")
            await bot.send_message(partner_id, f"💬 {message.text}")

        elif message.photo:
            fid = message.photo[-1].file_id
            db.add_message(chat_id, sender_id, message.caption or "", "photo", fid)
            await bot.send_photo(partner_id, fid, caption=message.caption)

        elif message.video:
            fid = message.video.file_id
            db.add_message(chat_id, sender_id, message.caption or "", "video", fid)
            await bot.send_video(partner_id, fid, caption=message.caption)

        elif message.voice:
            fid = message.voice.file_id
            db.add_message(chat_id, sender_id, "🎤", "voice", fid)
            await bot.send_voice(partner_id, fid)

        elif message.video_note:
            fid = message.video_note.file_id
            db.add_message(chat_id, sender_id, "⭕", "video_note", fid)
            await bot.send_video_note(partner_id, fid)

        elif message.sticker:
            fid = message.sticker.file_id
            db.add_message(chat_id, sender_id, "🎭", "sticker", fid)
            await bot.send_sticker(partner_id, fid)

        elif message.animation:
            fid = message.animation.file_id
            db.add_message(chat_id, sender_id, "🎞", "animation", fid)
            await bot.send_animation(partner_id, fid, caption=message.caption)

        elif message.document:
            fid = message.document.file_id
            db.add_message(chat_id, sender_id, message.caption or "📄", "document", fid)
            await bot.send_document(partner_id, fid, caption=message.caption)

        elif message.audio:
            fid = message.audio.file_id
            db.add_message(chat_id, sender_id, "🎵", "audio", fid)
            await bot.send_audio(partner_id, fid)

        else:
            await message.answer("⚠️ Этот тип сообщений не поддерживается.")

    except TelegramForbiddenError:
        await message.answer("❌ Собеседник заблокировал бота.")
        await state.clear()

# ── Заблокировать и закрыть ───────────────────────────────────────────────────

@router.callback_query(F.data.startswith("reportreason:"))
async def report_reason(callback: CallbackQuery):
    _, chat_id, reason = callback.data.split(":")
    chat_id = int(chat_id)
    chat    = db.get_chat(chat_id)
    if not chat:
        await callback.answer("Чат не найден", show_alert=True)
        return
    reported_id = chat["sender_id"] if callback.from_user.id == chat["target_id"] else chat["target_id"]
    db.add_report(chat_id, callback.from_user.id, reported_id, reason)
    await callback.message.edit_text("✅ Жалоба отправлена. Спасибо!")
    await callback.answer()

@router.callback_query(F.data == "cancel_report")
async def cancel_report(callback: CallbackQuery):
    await callback.message.delete()
    await callback.answer()

# ── КМН из меню чата ──────────────────────────────────────────────────────────

@router.message(ChatFSM.active, F.text == "🎮 КМН")
async def kmn_from_menu(message: Message, state: FSMContext):
    data    = await state.get_data()
    chat_id = data.get("active_chat")
    if not chat_id:
        await message.answer("Нет активного чата.")
        return
    from keyboards import chat_kmn_kb
    await message.answer(
        "🎮 <b>Камень-ножницы-бумага</b>\n\n"
        "Сыграй с собеседником на ставку!\n"
        "Проигравший автоматически отправляет своё медиа победителю.\n\n"
        "Игра до <b>3 побед</b> (лучший из 5 раундов).\n"
        "На каждый ход — <b>60 секунд</b>, иначе засчитывается поражение.",
        parse_mode="HTML",
        reply_markup=chat_kmn_kb(chat_id)
    )
