import time
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

import database as db
from config import ADMIN_IDS, BAN_DURATIONS, INTERESTS_DISPLAY
from keyboards import admin_ban_kb

router = Router()

def adm(user_id: int) -> bool:
    return user_id in ADMIN_IDS

GENDER_MAP = {"male": "👦 Парень", "female": "👧 Девушка", "other": "⚧ Другое"}

class AdminFSM(StatesGroup):
    broadcast = State()

# ── Меню ──────────────────────────────────────────────────────────────────────

@router.message(Command("admin"))
async def admin_menu(message: Message):
    if not adm(message.from_user.id): return
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    users = db.get_all_users()
    chats = db.get_all_chats_admin()
    reports = db.get_reports("new")
    profiles = db.get_active_profiles_admin()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Пользователи", callback_data="adm:users"),
         InlineKeyboardButton(text="📋 Анкеты", callback_data="adm:profiles")],
        [InlineKeyboardButton(text="💬 Чаты", callback_data="adm:chats"),
         InlineKeyboardButton(text=f"⚠️ Жалобы ({len(reports)})", callback_data="adm:reports")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="adm:broadcast")],
    ])
    await message.answer(
        f"🔐 <b>Beem Admin</b>\n\n"
        f"👥 Пользователей: <b>{len(users)}</b>\n"
        f"📋 Активных анкет: <b>{len(profiles)}</b>\n"
        f"💬 Чатов: <b>{len(chats)}</b>\n"
        f"⚠️ Новых жалоб: <b>{len(reports)}</b>",
        parse_mode="HTML", reply_markup=kb
    )

# ── Пользователи ──────────────────────────────────────────────────────────────

@router.callback_query(F.data == "adm:users")
async def adm_users(callback: CallbackQuery):
    if not adm(callback.from_user.id): return
    users = db.get_all_users()
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    rows = []
    for u in users[:20]:
        ban_icon = "🔒 " if u.get("banned") else ""
        rows.append([InlineKeyboardButton(
            text=f"{ban_icon}{u['name']}, {u['age']}л | @{u.get('username') or '—'}",
            callback_data=f"adm:user:{u['user_id']}"
        )])
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="adm:menu")])
    await callback.message.edit_text(
        f"👥 <b>Пользователи ({len(users)})</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("adm:user:"))
async def adm_user_detail(callback: CallbackQuery):
    if not adm(callback.from_user.id): return
    user_id = int(callback.data.split(":")[2])
    u = db.get_user(user_id)
    if not u:
        await callback.answer("Не найден", show_alert=True)
        return
    interests = ", ".join(INTERESTS_DISPLAY.get(i, i) for i in (u.get("interests") or "").split(",") if i)
    ban_status = "🔒 Заблокирован" if u.get("banned") else "✅ Активен"
    ban_until = ""
    if u.get("ban_until"):
        t = time.strftime("%d.%m.%Y %H:%M", time.localtime(u["ban_until"]))
        ban_until = f"\nДо: {t}"

    text = (
        f"👤 <b>{u['name']}</b>\n"
        f"ID: <code>{user_id}</code>\n"
        f"@{u.get('username') or '—'}\n"
        f"Возраст: {u.get('age')}\n"
        f"Пол: {GENDER_MAP.get(u.get('gender'), '—')}\n"
        f"Интересы: {interests}\n"
        f"Статус: {ban_status}{ban_until}\n"
        f"Причина бана: {u.get('ban_reason') or '—'}"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=admin_ban_kb(user_id))
    await callback.answer()

# ── Бан / Разбан ──────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("ban:"))
async def adm_ban(callback: CallbackQuery, bot: Bot):
    if not adm(callback.from_user.id): return
    _, user_id, duration = callback.data.split(":")
    user_id = int(user_id)
    label = BAN_DURATIONS[duration][0]
    db.ban_user(user_id, duration, reason="Нарушение правил")
    # Удалить анкету
    db.delete_active_profile(user_id)
    try:
        await bot.send_message(user_id, f"🚫 Ты заблокирован на {label}.")
    except: pass
    await callback.answer(f"✅ Забанен на {label}", show_alert=True)
    await callback.message.edit_text(f"🔒 Пользователь {user_id} забанен на {label}.")

@router.callback_query(F.data.startswith("unban:"))
async def adm_unban(callback: CallbackQuery, bot: Bot):
    if not adm(callback.from_user.id): return
    user_id = int(callback.data.split(":")[1])
    db.unban_user(user_id)
    try:
        await bot.send_message(user_id, "✅ Ты разблокирован!")
    except: pass
    await callback.answer("✅ Разбанен!", show_alert=True)
    await callback.message.edit_text(f"✅ Пользователь {user_id} разблокирован.")

# ── Анкеты ────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "adm:profiles")
async def adm_profiles(callback: CallbackQuery):
    if not adm(callback.from_user.id): return
    profiles = db.get_active_profiles_admin()
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    rows = []
    for p in profiles[:15]:
        rows.append([InlineKeyboardButton(
            text=f"{p['name']}, {p['age']}л — {p['description'][:30]}...",
            callback_data=f"adm:user:{p['user_id']}"
        )])
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="adm:menu")])
    await callback.message.edit_text(
        f"📋 <b>Активные анкеты ({len(profiles)})</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
    )
    await callback.answer()

# ── Чаты ─────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "adm:chats")
async def adm_chats(callback: CallbackQuery):
    if not adm(callback.from_user.id): return
    chats = db.get_all_chats_admin()
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    rows = []
    for c in chats[:20]:
        sn = c.get("sender_name") or f"ID:{c['sender_id']}"
        tn = c.get("target_name") or f"ID:{c['target_id']}"
        rows.append([InlineKeyboardButton(
            text=f"#{c['id']} {sn} → {tn} ({c.get('msg_count',0)} сооб.)",
            callback_data=f"adm:chat:{c['id']}"
        )])
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="adm:menu")])
    await callback.message.edit_text(
        f"💬 <b>Чаты ({len(chats)})</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("adm:chat:"))
async def adm_chat_detail(callback: CallbackQuery, bot: Bot):
    if not adm(callback.from_user.id): return
    chat_id = int(callback.data.split(":")[2])
    chat = db.get_chat(chat_id)
    if not chat:
        await callback.answer("Не найден", show_alert=True)
        return

    messages = db.get_chat_messages(chat_id, limit=50)
    sender = db.get_user(chat["sender_id"])
    target = db.get_user(chat["target_id"])
    sn = sender["name"] if sender else f"ID:{chat['sender_id']}"
    tn = target["name"] if target else f"ID:{chat['target_id']}"

    await callback.message.answer(
        f"💬 <b>Чат #{chat_id}</b>\n"
        f"📨 {sn} (ID:{chat['sender_id']}) → 📬 {tn} (ID:{chat['target_id']})\n"
        f"Сообщений: {len(messages)}\n"
        f"──────────────────",
        parse_mode="HTML"
    )

    # Пересылаем сообщения включая медиа
    for m in messages[-30:]:
        who = sn if m["sender_id"] == chat["sender_id"] else tn
        ts = time.strftime("%d.%m %H:%M", time.localtime(m["created_at"]))
        try:
            if m["msg_type"] == "text":
                await bot.send_message(
                    callback.from_user.id,
                    f"[{ts}] <b>{who}:</b> {m['content']}", parse_mode="HTML"
                )
            elif m["msg_type"] == "photo":
                await bot.send_photo(callback.from_user.id, m["file_id"], caption=f"[{ts}] 🖼 {who}")
            elif m["msg_type"] == "video":
                await bot.send_video(callback.from_user.id, m["file_id"], caption=f"[{ts}] 🎬 {who}")
            elif m["msg_type"] == "voice":
                await bot.send_voice(callback.from_user.id, m["file_id"], caption=f"[{ts}] 🎤 {who}")
            elif m["msg_type"] == "video_note":
                await bot.send_video_note(callback.from_user.id, m["file_id"])
                await bot.send_message(callback.from_user.id, f"[{ts}] ⭕ {who}")
            elif m["msg_type"] == "sticker":
                await bot.send_sticker(callback.from_user.id, m["file_id"])
                await bot.send_message(callback.from_user.id, f"[{ts}] 🎭 {who}")
            elif m["msg_type"] == "animation":
                await bot.send_animation(callback.from_user.id, m["file_id"], caption=f"[{ts}] 🎞 {who}")
            elif m["msg_type"] == "document":
                await bot.send_document(callback.from_user.id, m["file_id"], caption=f"[{ts}] 📄 {who}")
            elif m["msg_type"] == "audio":
                await bot.send_audio(callback.from_user.id, m["file_id"], caption=f"[{ts}] 🎵 {who}")
        except Exception:
            await bot.send_message(callback.from_user.id, f"[{ts}] {who}: [{m['msg_type']}]")

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    await bot.send_message(
        callback.from_user.id,
        f"— Конец чата #{chat_id} —",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"🔒 Бан {sn}", callback_data=f"adm:user:{chat['sender_id']}"),
             InlineKeyboardButton(text=f"🔒 Бан {tn}", callback_data=f"adm:user:{chat['target_id']}")]
        ])
    )
    await callback.answer()

# ── Жалобы ────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "adm:reports")
async def adm_reports(callback: CallbackQuery):
    if not adm(callback.from_user.id): return
    reports = db.get_reports("new")
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    if not reports:
        await callback.message.edit_text("✅ Новых жалоб нет!")
        await callback.answer()
        return
    rows = []
    for r in reports[:15]:
        name = r.get("reported_name") or f"ID:{r['reported_id']}"
        rows.append([InlineKeyboardButton(
            text=f"⚠️ На {name} | {r.get('reason','—')}",
            callback_data=f"adm:report:{r['id']}"
        )])
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="adm:menu")])
    await callback.message.edit_text(
        f"⚠️ <b>Жалобы ({len(reports)})</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("adm:report:"))
async def adm_report_detail(callback: CallbackQuery):
    if not adm(callback.from_user.id): return
    report_id = int(callback.data.split(":")[2])
    reports = db.get_reports()
    r = next((x for x in reports if x["id"] == report_id), None)
    if not r:
        await callback.answer("Не найдено", show_alert=True)
        return
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    ts = time.strftime("%d.%m.%Y %H:%M", time.localtime(r["created_at"]))
    await callback.message.edit_text(
        f"⚠️ <b>Жалоба #{report_id}</b>\n\n"
        f"На: {r.get('reported_name')} (ID:{r['reported_id']})\n"
        f"Причина: {r.get('reason', '—')}\n"
        f"Чат: #{r['chat_id']}\n"
        f"Время: {ts}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔒 Забанить", callback_data=f"adm:user:{r['reported_id']}"),
             InlineKeyboardButton(text="✅ Закрыть", callback_data=f"adm:resolvereport:{report_id}")],
            [InlineKeyboardButton(text="💬 Открыть чат", callback_data=f"adm:chat:{r['chat_id']}")],
        ])
    )
    await callback.answer()

@router.callback_query(F.data.startswith("adm:resolvereport:"))
async def adm_resolve_report(callback: CallbackQuery):
    if not adm(callback.from_user.id): return
    report_id = int(callback.data.split(":")[2])
    db.resolve_report(report_id)
    await callback.answer("✅ Жалоба закрыта", show_alert=True)
    await callback.message.edit_text("✅ Жалоба закрыта.")

# ── Рассылка ──────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "adm:broadcast")
async def adm_broadcast_start(callback: CallbackQuery, state: FSMContext):
    if not adm(callback.from_user.id): return
    await callback.message.answer("📢 Напиши текст рассылки:")
    await state.set_state(AdminFSM.broadcast)
    await callback.answer()

@router.message(AdminFSM.broadcast)
async def adm_do_broadcast(message: Message, state: FSMContext, bot: Bot):
    if not adm(message.from_user.id): return
    await state.clear()
    users = db.get_all_users()
    sent = failed = 0
    for u in users:
        try:
            await bot.send_message(u["user_id"], f"📢 <b>Объявление от Beem:</b>\n\n{message.text}", parse_mode="HTML")
            sent += 1
        except: failed += 1
    await message.answer(f"📢 Рассылка завершена:\n✅ Доставлено: {sent}\n❌ Ошибок: {failed}")

@router.callback_query(F.data == "adm:menu")
async def adm_back_menu(callback: CallbackQuery):
    if not adm(callback.from_user.id): return
    await callback.answer()
    await admin_menu.__wrapped__(callback.message) if hasattr(admin_menu, '__wrapped__') else None
    # Просто показываем меню заново
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    users = db.get_all_users()
    chats = db.get_all_chats_admin()
    reports = db.get_reports("new")
    profiles = db.get_active_profiles_admin()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Пользователи", callback_data="adm:users"),
         InlineKeyboardButton(text="📋 Анкеты", callback_data="adm:profiles")],
        [InlineKeyboardButton(text="💬 Чаты", callback_data="adm:chats"),
         InlineKeyboardButton(text=f"⚠️ Жалобы ({len(reports)})", callback_data="adm:reports")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="adm:broadcast")],
    ])
    await callback.message.edit_text(
        f"🔐 <b>Beem Admin</b>\n\n"
        f"👥 Пользователей: <b>{len(users)}</b>\n"
        f"📋 Активных анкет: <b>{len(profiles)}</b>\n"
        f"💬 Чатов: <b>{len(chats)}</b>\n"
        f"⚠️ Новых жалоб: <b>{len(reports)}</b>",
        parse_mode="HTML", reply_markup=kb
    )
