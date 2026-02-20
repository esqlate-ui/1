"""
КМН (Камень-ножницы-бумага) с медиа-ставками.

Статусы игры:
  waiting_stake   — соперник ещё не загрузил ставку
  waiting_move    — оба ставки загружены, ждём ходов раунда
  finished        — игра завершена
  cancelled       — отменена (таймаут / отказ)

Ходы сохраняются в initiator_move / opponent_move.
Когда оба хода есть — бот сам раскрывает раунд.
"""

import asyncio
import time
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramForbiddenError

import database as db

router = Router()

MOVE_EMOJI = {"rock": "✊", "scissors": "✌️", "paper": "🖐"}
WINS_AGAINST = {"rock": "scissors", "scissors": "paper", "paper": "rock"}
MOVE_TIMEOUT = 60  # секунд на ход

# ── FSM для загрузки ставки ───────────────────────────────────────────────────

class RpsFSM(StatesGroup):
    uploading_stake = State()   # ждём медиа от инициатора (уже задано в чате)
    opponent_stake  = State()   # ждём медиа от соперника

# ── Вспомогательные ──────────────────────────────────────────────────────────

def _rps_move_kb(game_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✊", callback_data=f"rps:move:{game_id}:rock"),
        InlineKeyboardButton(text="✌️", callback_data=f"rps:move:{game_id}:scissors"),
        InlineKeyboardButton(text="🖐",  callback_data=f"rps:move:{game_id}:paper"),
    ]])

def _rps_accept_kb(game_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Принять вызов", callback_data=f"rps:accept:{game_id}"),
        InlineKeyboardButton(text="❌ Отклонить",     callback_data=f"rps:decline:{game_id}"),
    ]])

async def _send_stake(bot: Bot, user_id: int, stake_type: str, stake_fid: str, caption: str = ""):
    """Отправить ставку победителю."""
    try:
        if stake_type == "photo":
            await bot.send_photo(user_id, stake_fid, caption=caption)
        elif stake_type == "video":
            await bot.send_video(user_id, stake_fid, caption=caption)
        elif stake_type == "voice":
            await bot.send_voice(user_id, stake_fid)
            if caption:
                await bot.send_message(user_id, caption)
    except TelegramForbiddenError:
        pass

async def _resolve_round(bot: Bot, game_id: int):
    """Раскрыть раунд когда оба хода сделаны."""
    game = db.get_rps_game(game_id)
    if not game:
        return
    if game["status"] != "waiting_move":
        return
    if not game["initiator_move"] or not game["opponent_move"]:
        return

    im = game["initiator_move"]
    om = game["opponent_move"]
    ie = MOVE_EMOJI[im]
    oe = MOVE_EMOJI[om]

    iw = game["initiator_wins"]
    ow = game["opponent_wins"]

    if im == om:
        result_i = result_o = "🤝 Ничья"
    elif WINS_AGAINST[im] == om:
        iw += 1
        result_i = f"🏆 Ты победил раунд! ({ie} > {oe})"
        result_o = f"💀 Ты проиграл раунд. ({oe} < {ie})"
    else:
        ow += 1
        result_i = f"💀 Ты проиграл раунд. ({ie} < {oe})"
        result_o = f"🏆 Ты победил раунд! ({oe} > {ie})"

    wins_to = game["wins_to"]
    game_over = iw >= wins_to or ow >= wins_to

    score_txt = f"Счёт: {iw}:{ow} (до {wins_to} побед)"

    if game_over:
        db.update_rps_game(game_id,
            initiator_wins=iw, opponent_wins=ow,
            initiator_move=None, opponent_move=None,
            status="finished"
        )
        if iw >= wins_to:
            # Инициатор победил — получает ставку соперника
            winner_id = game["initiator_id"]
            loser_id  = game["opponent_id"]
            winner_stake_type = game["opponent_stake_type"]
            winner_stake_fid  = game["opponent_stake_fid"]
            winner_msg = f"🎉 <b>Ты победил в КМН!</b>\n{score_txt}\n\nВот твой приз 👇"
            loser_msg  = f"😔 <b>Ты проиграл в КМН.</b>\n{score_txt}\n\nСтавка отправлена победителю."
        else:
            winner_id = game["opponent_id"]
            loser_id  = game["initiator_id"]
            winner_stake_type = game["initiator_stake_type"]
            winner_stake_fid  = game["initiator_stake_fid"]
            winner_msg = f"🎉 <b>Ты победил в КМН!</b>\n{score_txt}\n\nВот твой приз 👇"
            loser_msg  = f"😔 <b>Ты проиграл в КМН.</b>\n{score_txt}\n\nСтавка отправлена победителю."

        try:
            await bot.send_message(winner_id, winner_msg, parse_mode="HTML")
            await _send_stake(bot, winner_id, winner_stake_type, winner_stake_fid)
        except TelegramForbiddenError:
            pass
        try:
            await bot.send_message(loser_id, loser_msg, parse_mode="HTML")
        except TelegramForbiddenError:
            pass
    else:
        # Сбрасываем ходы, следующий раунд
        db.update_rps_game(game_id,
            initiator_wins=iw, opponent_wins=ow,
            initiator_move=None, opponent_move=None,
            status="waiting_move"
        )
        try:
            await bot.send_message(
                game["initiator_id"],
                f"{result_i}\n{score_txt}\n\n⚡ Следующий раунд — сделай ход:",
                parse_mode="HTML",
                reply_markup=_rps_move_kb(game_id)
            )
        except TelegramForbiddenError:
            pass
        try:
            await bot.send_message(
                game["opponent_id"],
                f"{result_o}\n{score_txt}\n\n⚡ Следующий раунд — сделай ход:",
                parse_mode="HTML",
                reply_markup=_rps_move_kb(game_id)
            )
        except TelegramForbiddenError:
            pass

async def _timeout_move(bot: Bot, game_id: int, user_id: int, opponent_id: int, delay: int = 60):
    """Через delay секунд — если ход не сделан, засчитать поражение."""
    await asyncio.sleep(delay)
    game = db.get_rps_game(game_id)
    if not game or game["status"] != "waiting_move":
        return

    is_initiator = (user_id == game["initiator_id"])
    move_field   = "initiator_move" if is_initiator else "opponent_move"
    if game.get(move_field):
        return  # уже сделал ход

    # Засчитываем победу сопернику
    iw = game["initiator_wins"]
    ow = game["opponent_wins"]
    wins_to = game["wins_to"]

    if is_initiator:
        ow += 1
    else:
        iw += 1

    game_over = iw >= wins_to or ow >= wins_to
    score_txt = f"Счёт: {iw}:{ow}"

    if game_over:
        db.update_rps_game(game_id,
            initiator_wins=iw, opponent_wins=ow,
            initiator_move=None, opponent_move=None,
            status="finished"
        )
        if iw >= wins_to:
            winner_id = game["initiator_id"]
            loser_id  = game["opponent_id"]
            winner_stake_type = game["opponent_stake_type"]
            winner_stake_fid  = game["opponent_stake_fid"]
        else:
            winner_id = game["opponent_id"]
            loser_id  = game["initiator_id"]
            winner_stake_type = game["initiator_stake_type"]
            winner_stake_fid  = game["initiator_stake_fid"]

        try:
            await bot.send_message(loser_id,
                f"⏰ <b>Время вышло!</b> Ход не сделан — засчитано поражение.\n{score_txt}",
                parse_mode="HTML")
        except TelegramForbiddenError:
            pass
        try:
            await bot.send_message(winner_id,
                f"🎉 <b>Соперник не сделал ход вовремя — ты победил!</b>\n{score_txt}\n\nВот твой приз 👇",
                parse_mode="HTML")
            await _send_stake(bot, winner_id, winner_stake_type, winner_stake_fid)
        except TelegramForbiddenError:
            pass
    else:
        db.update_rps_game(game_id,
            initiator_wins=iw, opponent_wins=ow,
            initiator_move=None, opponent_move=None,
            status="waiting_move"
        )
        try:
            await bot.send_message(user_id,
                f"⏰ <b>Время вышло!</b> Раунд проигран.\n{score_txt}\n\nСледующий раунд — сделай ход:",
                parse_mode="HTML", reply_markup=_rps_move_kb(game_id))
        except TelegramForbiddenError:
            pass
        try:
            await bot.send_message(opponent_id,
                f"⏰ Соперник не успел — раунд твой!\n{score_txt}\n\nСледующий раунд — сделай ход:",
                parse_mode="HTML", reply_markup=_rps_move_kb(game_id))
        except TelegramForbiddenError:
            pass

async def _timeout_accept(bot: Bot, game_id: int, initiator_id: int, opponent_id: int, delay: int = 60):
    """Если соперник не принял вызов — отмена."""
    await asyncio.sleep(delay)
    game = db.get_rps_game(game_id)
    if not game or game["status"] != "waiting_stake":
        return
    db.update_rps_game(game_id, status="cancelled")
    try:
        await bot.send_message(initiator_id,
            "⏰ Соперник не принял вызов вовремя. Игра отменена.")
    except TelegramForbiddenError:
        pass
    try:
        await bot.send_message(opponent_id,
            "⏰ Время на принятие вызова истекло. Игра отменена.")
    except TelegramForbiddenError:
        pass

# ── Запуск КМН из чата ────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("rps:start:"))
async def rps_start(callback: CallbackQuery, state: FSMContext):
    """Кнопка «🎮 КМН» в меню чата."""
    chat_id = int(callback.data.split(":")[2])
    chat    = db.get_chat(chat_id)
    if not chat:
        await callback.answer("Чат не найден", show_alert=True)
        return
    if chat.get("closed"):
        await callback.answer("Чат закрыт", show_alert=True)
        return

    # Проверяем нет ли активной игры
    existing = db.get_active_rps_by_chat(chat_id)
    if existing:
        await callback.answer("В этом чате уже идёт игра!", show_alert=True)
        return

    partner = chat["sender_id"] if callback.from_user.id == chat["target_id"] else chat["target_id"]

    await state.update_data(rps_chat_id=chat_id, rps_opponent=partner)
    await state.set_state(RpsFSM.uploading_stake)

    await callback.message.answer(
        "🎮 <b>КМН — загрузи ставку</b>\n\n"
        "Отправь фото, видео или голосовое которое получит соперник если победит.\n"
        "Файл хранится у бота до конца игры — соперник его не увидит пока не выиграет.\n\n"
        "⏰ На загрузку 60 секунд.",
        parse_mode="HTML"
    )
    await callback.answer()

@router.message(RpsFSM.uploading_stake)
async def rps_initiator_stake(message: Message, state: FSMContext, bot: Bot):
    """Инициатор загружает ставку."""
    stake_type = None
    stake_fid  = None

    if message.photo:
        stake_type = "photo"
        stake_fid  = message.photo[-1].file_id
    elif message.video:
        stake_type = "video"
        stake_fid  = message.video.file_id
    elif message.voice:
        stake_type = "voice"
        stake_fid  = message.voice.file_id
    else:
        await message.answer("Отправь фото, видео или голосовое.")
        return

    data       = await state.get_data()
    chat_id    = data["rps_chat_id"]
    opponent   = data["rps_opponent"]
    initiator  = message.from_user.id

    # Создаём игру в БД
    game_id = db.create_rps_game(
        chat_id=chat_id,
        initiator_id=initiator,
        opponent_id=opponent,
        initiator_stake_type=stake_type,
        initiator_stake_fid=stake_fid,
        wins_to=3
    )
    await state.clear()

    await message.answer(
        "✅ <b>Ставка принята!</b>\n\nОтправляю вызов сопернику...",
        parse_mode="HTML"
    )

    # Уведомляем соперника
    try:
        await bot.send_message(
            opponent,
            "🎮 <b>Тебе бросили вызов в КМН!</b>\n\n"
            "Игра до 3 побед. Проигравший отдаёт своё медиа.\n"
            "Если примешь — загрузи свою ставку (фото/видео/голосовое).\n\n"
            "⏰ У тебя 60 секунд на решение.",
            parse_mode="HTML",
            reply_markup=_rps_accept_kb(game_id)
        )
    except TelegramForbiddenError:
        await message.answer("❌ Не удалось отправить вызов — соперник недоступен.")
        db.update_rps_game(game_id, status="cancelled")
        return

    # Таймаут на принятие вызова
    asyncio.create_task(
        _timeout_accept(bot, game_id, initiator, opponent, delay=60)
    )

# ── Принять / Отклонить вызов ─────────────────────────────────────────────────

@router.callback_query(F.data.startswith("rps:accept:"))
async def rps_accept(callback: CallbackQuery, state: FSMContext):
    game_id = int(callback.data.split(":")[2])
    game    = db.get_rps_game(game_id)
    if not game or game["status"] != "waiting_stake":
        await callback.answer("Игра уже недоступна", show_alert=True)
        return
    if callback.from_user.id != game["opponent_id"]:
        await callback.answer("Это не твой вызов", show_alert=True)
        return

    await state.update_data(rps_game_id=game_id)
    await state.set_state(RpsFSM.opponent_stake)

    await callback.message.edit_text(
        "✅ Вызов принят!\n\n"
        "🎮 <b>Загрузи свою ставку</b> — фото, видео или голосовое.\n"
        "⏰ 60 секунд.",
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data.startswith("rps:decline:"))
async def rps_decline(callback: CallbackQuery, bot: Bot):
    game_id = int(callback.data.split(":")[2])
    game    = db.get_rps_game(game_id)
    if not game:
        await callback.answer("Игра не найдена", show_alert=True)
        return
    db.update_rps_game(game_id, status="cancelled")
    await callback.message.edit_text("❌ Ты отклонил вызов.")
    await callback.answer()
    try:
        await bot.send_message(
            game["initiator_id"],
            "❌ Соперник отклонил вызов в КМН."
        )
    except TelegramForbiddenError:
        pass

# ── Соперник загружает ставку ─────────────────────────────────────────────────

@router.message(RpsFSM.opponent_stake)
async def rps_opponent_stake(message: Message, state: FSMContext, bot: Bot):
    stake_type = None
    stake_fid  = None

    if message.photo:
        stake_type = "photo"
        stake_fid  = message.photo[-1].file_id
    elif message.video:
        stake_type = "video"
        stake_fid  = message.video.file_id
    elif message.voice:
        stake_type = "voice"
        stake_fid  = message.voice.file_id
    else:
        await message.answer("Отправь фото, видео или голосовое.")
        return

    data    = await state.get_data()
    game_id = data["rps_game_id"]
    game    = db.get_rps_game(game_id)
    if not game or game["status"] != "waiting_stake":
        await message.answer("Игра уже недоступна.")
        await state.clear()
        return

    db.update_rps_game(game_id,
        opponent_stake_type=stake_type,
        opponent_stake_fid=stake_fid,
        status="waiting_move"
    )
    await state.clear()

    await message.answer(
        "✅ <b>Ставки приняты! Игра начинается!</b>\n\n"
        "🎮 КМН — лучший из 5 раундов (до 3 побед)\n\n"
        "Сделай первый ход 👇",
        parse_mode="HTML",
        reply_markup=_rps_move_kb(game_id)
    )

    try:
        await bot.send_message(
            game["initiator_id"],
            "✅ <b>Соперник загрузил ставку! Игра начинается!</b>\n\n"
            "🎮 КМН — лучший из 5 раундов (до 3 побед)\n\n"
            "Сделай первый ход 👇",
            parse_mode="HTML",
            reply_markup=_rps_move_kb(game_id)
        )
    except TelegramForbiddenError:
        pass

    # Таймаут на первый ход
    asyncio.create_task(
        _timeout_move(bot, game_id, game["initiator_id"], game["opponent_id"], MOVE_TIMEOUT)
    )
    asyncio.create_task(
        _timeout_move(bot, game_id, game["opponent_id"], game["initiator_id"], MOVE_TIMEOUT)
    )

# ── Ход в раунде ──────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("rps:move:"))
async def rps_move(callback: CallbackQuery, bot: Bot):
    _, _, game_id_str, move = callback.data.split(":")
    game_id = int(game_id_str)
    game    = db.get_rps_game(game_id)

    if not game or game["status"] != "waiting_move":
        await callback.answer("Игра завершена или недоступна", show_alert=True)
        return

    uid = callback.from_user.id
    is_initiator = (uid == game["initiator_id"])
    is_opponent  = (uid == game["opponent_id"])

    if not is_initiator and not is_opponent:
        await callback.answer("Ты не участник этой игры", show_alert=True)
        return

    move_field = "initiator_move" if is_initiator else "opponent_move"
    if game.get(move_field):
        await callback.answer("Ты уже сделал ход! Ждём соперника...", show_alert=True)
        return

    db.update_rps_game(game_id, **{move_field: move})
    await callback.message.edit_text(
        f"✅ Ход принят: {MOVE_EMOJI[move]}\n\nОжидаем соперника... ⏳",
        reply_markup=None
    )
    await callback.answer(f"Ход {MOVE_EMOJI[move]} принят!")

    # Проверяем — оба ли сделали ход
    game = db.get_rps_game(game_id)
    if game["initiator_move"] and game["opponent_move"]:
        await _resolve_round(bot, game_id)
    else:
        # Запускаем таймаут для соперника
        other_id = game["opponent_id"] if is_initiator else game["initiator_id"]
        asyncio.create_task(
            _timeout_move(bot, game_id, other_id,
                          uid, MOVE_TIMEOUT)
        )
