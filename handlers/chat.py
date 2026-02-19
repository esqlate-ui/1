from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramForbiddenError

import database as db
from keyboards import chat_kb, report_reason_kb, my_chats_kb, main_kb

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
        f"💬 <b>Чат открыт!</b>\n\n"
        f"Пиши — собеседник не знает кто ты.\n"
        f"Можно отправлять текст, фото, видео, голосовые, кружки, стикеры, гифки.\n\n"
        f"<i>/exit — выйти из чата</i>",
        parse_mode="HTML"
    )
    await callback.answer()

    try:
        target_user = db.get_user(target_id)
        await bot.send_message(
            target_id,
            f"📬 <b>Кто-то написал тебе!</b>\n\nНажми «Ответить» чтобы написать в ответ:",
            parse_mode="HTML",
            reply_markup=chat_kb(chat_id)
        )
    except (TelegramForbiddenError, Exception):
        pass

# ── Открыть чат по ID (из списка чатов) ──────────────────────────────────────

@router.callback_query(F.data.startswith("openchatid:"))
async def open_chat_by_id(callback: CallbackQuery, state: FSMContext, bot: Bot):
    chat_id = int(callback.data.split(":")[1])
    chat = db.get_chat(chat_id)
    if not chat or callback.from_user.id not in (chat["sender_id"], chat["target_id"]):
        await callback.answer("Нет доступа", show_alert=True)
        return

    partner = chat["sender_id"] if callback.from_user.id == chat["target_id"] else chat["target_id"]
    await state.update_data(active_chat=chat_id, chat_partner=partner)
    await state.set_state(ChatFSM.active)

    messages = db.get_chat_messages(chat_id, limit=20)
    if messages:
        await callback.message.answer(f"💬 <b>Чат #{chat_id} — последние сообщения:</b>", parse_mode="HTML")
        for m in messages[-10:]:
            who = "Ты" if m["sender_id"] == callback.from_user.id else "Собеседник"
            if m["msg_type"] == "text":
                await callback.message.answer(f"<b>{who}:</b> {m['content']}", parse_mode="HTML")
    await callback.message.answer(
        "Чат активен. Пиши сообщения!\n<i>/exit — выйти</i>",
        parse_mode="HTML",
        reply_markup=chat_kb(chat_id)
    )
    await callback.answer()

# ── Ответить (кнопка под уведомлением) ───────────────────────────────────────

@router.callback_query(F.data.startswith("reply:"))
async def reply_to_chat(callback: CallbackQuery, state: FSMContext):
    chat_id = int(callback.data.split(":")[1])
    chat = db.get_chat(chat_id)
    if not chat or callback.from_user.id not in (chat["sender_id"], chat["target_id"]):
        await callback.answer("Нет доступа", show_alert=True)
        return
    partner = chat["sender_id"] if callback.from_user.id == chat["target_id"] else chat["target_id"]
    await state.update_data(active_chat=chat_id, chat_partner=partner)
    await state.set_state(ChatFSM.active)
    await callback.message.answer("💬 Чат активен. Пиши!\n<i>/exit — выйти</i>", parse_mode="HTML")
    await callback.answer()

# ── Выйти из чата ─────────────────────────────────────────────────────────────

@router.message(F.text == "/exit")
@router.message(ChatFSM.active, F.text == "/exit")
async def exit_chat(message: Message, state: FSMContext):
    await state.clear()
    profile = db.get_active_profile(message.from_user.id)
    await message.answer("👋 Вышел из чата.", reply_markup=main_kb(bool(profile)))

# ── Мои чаты ──────────────────────────────────────────────────────────────────

@router.message(F.text == "💬 Мои чаты")
async def my_chats(message: Message):
    chats = db.get_user_chats(message.from_user.id)
    if not chats:
        await message.answer("У тебя пока нет чатов.")
        return
    await message.answer("💬 <b>Твои чаты:</b>", parse_mode="HTML",
                         reply_markup=my_chats_kb(chats, message.from_user.id))

# ── Пересылка сообщений ───────────────────────────────────────────────────────

@router.message(ChatFSM.active)
async def relay(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    chat_id = data.get("active_chat")
    partner_id = data.get("chat_partner")
    if not chat_id or not partner_id:
        await state.clear()
        return

    if db.is_blocked(partner_id, message.from_user.id):
        await message.answer("🚫 Собеседник заблокировал тебя.")
        await state.clear()
        return

    sender_id = message.from_user.id

    try:
        if message.text:
            db.add_message(chat_id, sender_id, message.text, "text")
            await bot.send_message(partner_id, f"💬 {message.text}", reply_markup=chat_kb(chat_id))

        elif message.photo:
            fid = message.photo[-1].file_id
            db.add_message(chat_id, sender_id, message.caption or "", "photo", fid)
            await bot.send_photo(partner_id, fid, caption=message.caption, reply_markup=chat_kb(chat_id))

        elif message.video:
            fid = message.video.file_id
            db.add_message(chat_id, sender_id, message.caption or "", "video", fid)
            await bot.send_video(partner_id, fid, caption=message.caption, reply_markup=chat_kb(chat_id))

        elif message.voice:
            fid = message.voice.file_id
            db.add_message(chat_id, sender_id, "🎤", "voice", fid)
            await bot.send_voice(partner_id, fid)
            await bot.send_message(partner_id, "🎤 Голосовое:", reply_markup=chat_kb(chat_id))

        elif message.video_note:
            fid = message.video_note.file_id
            db.add_message(chat_id, sender_id, "⭕", "video_note", fid)
            await bot.send_video_note(partner_id, fid)
            await bot.send_message(partner_id, "⭕ Кружок:", reply_markup=chat_kb(chat_id))

        elif message.sticker:
            fid = message.sticker.file_id
            db.add_message(chat_id, sender_id, "🎭", "sticker", fid)
            await bot.send_sticker(partner_id, fid)
            await bot.send_message(partner_id, "🎭 Стикер:", reply_markup=chat_kb(chat_id))

        elif message.animation:
            fid = message.animation.file_id
            db.add_message(chat_id, sender_id, "🎞", "animation", fid)
            await bot.send_animation(partner_id, fid, caption=message.caption)
            await bot.send_message(partner_id, "🎞 Гифка:", reply_markup=chat_kb(chat_id))

        elif message.document:
            fid = message.document.file_id
            db.add_message(chat_id, sender_id, message.caption or "📄", "document", fid)
            await bot.send_document(partner_id, fid, caption=message.caption, reply_markup=chat_kb(chat_id))

        elif message.audio:
            fid = message.audio.file_id
            db.add_message(chat_id, sender_id, "🎵", "audio", fid)
            await bot.send_audio(partner_id, fid, reply_markup=chat_kb(chat_id))

        else:
            await message.answer("⚠️ Этот тип сообщений не поддерживается.")
            return

        await message.answer("✅")

    except TelegramForbiddenError:
        await message.answer("❌ Собеседник заблокировал бота.")
        await state.clear()

# ── Жалоба ────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("report:"))
async def report_start(callback: CallbackQuery):
    chat_id = int(callback.data.split(":")[1])
    await callback.message.answer("⚠️ Выбери причину жалобы:", reply_markup=report_reason_kb(chat_id))
    await callback.answer()

@router.callback_query(F.data.startswith("reportreason:"))
async def report_reason(callback: CallbackQuery):
    _, chat_id, reason = callback.data.split(":")
    chat_id = int(chat_id)
    chat = db.get_chat(chat_id)
    if not chat:
        await callback.answer("Чат не найден", show_alert=True)
        return
    reported_id = chat["sender_id"] if callback.from_user.id == chat["target_id"] else chat["target_id"]
    db.add_report(chat_id, callback.from_user.id, reported_id, reason)
    await callback.message.edit_text("✅ Жалоба отправлена на рассмотрение. Спасибо!")
    await callback.answer()

# ── Блокировка ────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("block:"))
async def block_from_chat(callback: CallbackQuery, state: FSMContext):
    chat_id = int(callback.data.split(":")[1])
    chat = db.get_chat(chat_id)
    if not chat or callback.from_user.id not in (chat["sender_id"], chat["target_id"]):
        await callback.answer("Нет доступа", show_alert=True)
        return
    blocked_id = chat["sender_id"] if callback.from_user.id == chat["target_id"] else chat["target_id"]
    db.block_user(callback.from_user.id, blocked_id)
    await state.clear()
    profile = db.get_active_profile(callback.from_user.id)
    await callback.message.answer(
        "🚫 Пользователь заблокирован. Его анкеты больше не будут тебе показываться.",
        reply_markup=main_kb(bool(profile))
    )
    await callback.answer()
