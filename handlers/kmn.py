"""
КМН (Камень-Ножницы-Бумага) — игра со ставками в чате.

Статусы игры:
  waiting_stake_initiator  — ждём ставку от инициатора
  waiting_stake_opponent   — ждём ставку от соперника (и принятие вызова)
  waiting_move_both        — оба ещё не сделали ход
  waiting_move_initiator   — инициатор не сделал ход (соперник уже сделал)
  waiting_move_opponent    — соперник не сделал ход (инициатор уже сделал)
  finished                 — игра окончена
  cancelled                — отменена (таймаут / отказ)
"""

import asyncio
import time
from aiogram import Router, F, Bot
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramForbiddenError

import database as db

router = Router()

MOVE_EMOJI = {"rock": "✊", "scissors": "✌️", "paper": "🖐"}
MOVE_NAME  = {"rock": "Камень", "scissors": "Ножницы", "paper": "Бумага"}
TIMEOUT_SEC = 60  # таймаут на каждый ход / принятие вызова

# Победитель раунда: None = ничья
def round_winner(m1: str, m2: str):
    wins = {"rock": "scissors", "scissors": "paper", "paper": "rock"}
    if m1 == m2:
        return None
    return "p1" if wins[m1] == m2 else "p2"

def move_kb(game_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✊", callback_data=f"kmn:move:{game_id}:rock"),
        InlineKeyboardButton(text="✌️", callback_data=f"kmn:move:{game_id}:scissors"),
        InlineKeyboardButton(text="🖐", callback_data=f"kmn:move:{game_id}:paper"),
    ]])

def accept_kb(game_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Принять вызов", callback_data=f"kmn:accept:{game_id}"),
        InlineKeyboardButton(text="❌ Отказать",      callback_data=f"kmn:decline:{game_id}"),
    ]])

class KmnFSM(StatesGroup):
    waiting_stake = State()   # ждём медиа-ставку

# ── Запуск КМН из чата ────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("kmn:start:"))
async def kmn_start(callback: CallbackQuery, state: FSMContext, bot: Bot):
    chat_id = int(callback.data.split(":")[2])
    chat    = db.get_chat(chat_id)
    if not chat or chat.get("closed"):
        await callback.answer("Чат недоступен.", show_alert=True)
        return

    user_id = callback.from_user.id
    if user_id not in (chat["sender_id"], chat["target_id"]):
        await callback.answer("Нет доступа.", show_alert=True)
        return

    # Проверяем нет ли уже активной игры
    existing = db.get_active_kmn_by_chat(chat_id)
    if existing:
        await callback.answer("В этом чате уже идёт игра!", show_alert=True)
        return

    opponent_id = chat["target_id"] if user_id == chat["sender_id"] else chat["sender_id"]
    game_id     = db.create_kmn_game(chat_id, user_id, opponent_id, wins_needed=3)

    # Сохраняем в FSM что ждём ставку
    await state.update_data(kmn_game_id=game_id, kmn_role="initiator")
    await state.set_state(KmnFSM.waiting_stake)

    await callback.message.answer(
        "🎮 <b>КМН со ставкой!</b>\n\n"
        "Сначала загрузи свою ставку — фото, видео или голосовое.\n"
        "Соперник увидит её только если <b>победит</b>.\n\n"
        "⏳ У тебя <b>60 секунд</b>.",
        parse_mode="HTML"
    )
    await callback.answer()

    # Таймаут на загрузку ставки инициатором
    asyncio.create_task(_timeout_stake(bot, game_id, user_id, opponent_id, TIMEOUT_SEC))

# ── Получение ставки от инициатора ────────────────────────────────────────────

@router.message(KmnFSM.waiting_stake)
async def kmn_receive_stake(message: Message, state: FSMContext, bot: Bot):
    data    = await state.get_data()
    game_id = data.get("kmn_game_id")
    role    = data.get("kmn_role")  # initiator | opponent
    if not game_id:
        return

    game = db.get_kmn_game(game_id)
    if not game or game["status"] not in (
        "waiting_stake_initiator", "waiting_stake_opponent"
    ):
        await state.set_state(None)
        return

    # Определяем file_id и тип
    file_id  = None
    media_type = None
    if message.photo:
        file_id, media_type = message.photo[-1].file_id, "photo"
    elif message.video:
        file_id, media_type = message.video.file_id, "video"
    elif message.voice:
        file_id, media_type = message.voice.file_id, "voice"
    else:
        await message.answer("⚠️ Отправь фото, видео или голосовое как ставку.")
        return

    if role == "initiator":
        db.update_kmn_game(game_id,
            initiator_stake_file_id=file_id,
            initiator_stake_type=media_type,
            status="waiting_stake_opponent"
        )
        await state.set_state(None)
        await message.answer(
            "✅ Ставка принята! Ожидаем соперника...\n\n"
            "Ему отправлен вызов — у него 60 секунд чтобы принять и загрузить ставку."
        )

        # Уведомляем соперника
        opponent_id = game["opponent_id"]
        try:
            await bot.send_message(
                opponent_id,
                f"⚔️ <b>Тебя вызвали на КМН!</b>\n\n"
                f"Ставка: любое медиа\n"
                f"До побед: 3\n\n"
                f"⏳ Есть <b>60 секунд</b> чтобы принять или отказаться.",
                parse_mode="HTML",
                reply_markup=accept_kb(game_id)
            )
        except TelegramForbiddenError:
            db.update_kmn_game(game_id, status="cancelled")
            await message.answer("❌ Соперник недоступен. Игра отменена.")

        asyncio.create_task(_timeout_accept(bot, game_id, game["initiator_id"], opponent_id, TIMEOUT_SEC))

    elif role == "opponent":
        db.update_kmn_game(game_id,
            opponent_stake_file_id=file_id,
            opponent_stake_type=media_type,
            status="waiting_move_both"
        )
        await state.set_state(None)
        await message.answer("✅ Ставка принята! Игра начинается!")

        # Стартуем первый раунд для обоих
        initiator_id = game["initiator_id"]
        await _send_round(bot, game_id, initiator_id, opponent_id=message.from_user.id)

# ── Принять / отклонить вызов ─────────────────────────────────────────────────

@router.callback_query(F.data.startswith("kmn:accept:"))
async def kmn_accept(callback: CallbackQuery, state: FSMContext, bot: Bot):
    game_id = int(callback.data.split(":")[2])
    game    = db.get_kmn_game(game_id)
    if not game or game["status"] != "waiting_stake_opponent":
        await callback.answer("Вызов уже недействителен.", show_alert=True)
        return
    if callback.from_user.id != game["opponent_id"]:
        await callback.answer("Это не твой вызов.", show_alert=True)
        return

    await state.update_data(kmn_game_id=game_id, kmn_role="opponent")
    await state.set_state(KmnFSM.waiting_stake)

    await callback.message.edit_text(
        "✅ Вызов принят!\n\n"
        "Теперь загрузи свою ставку — фото, видео или голосовое.\n"
        "⏳ У тебя <b>60 секунд</b>.",
        parse_mode="HTML"
    )
    await callback.answer()
    asyncio.create_task(_timeout_stake(bot, game_id, callback.from_user.id, game["initiator_id"], TIMEOUT_SEC, role="opponent"))

@router.callback_query(F.data.startswith("kmn:decline:"))
async def kmn_decline(callback: CallbackQuery, bot: Bot):
    game_id = int(callback.data.split(":")[2])
    game    = db.get_kmn_game(game_id)
    if not game:
        await callback.answer()
        return
    if callback.from_user.id != game["opponent_id"]:
        await callback.answer("Это не твой вызов.", show_alert=True)
        return

    db.update_kmn_game(game_id, status="cancelled")
    await callback.message.edit_text("❌ Ты отказался от игры.")
    await callback.answer()

    try:
        await bot.send_message(game["initiator_id"], "😔 Соперник отказался от КМН.")
    except:
        pass

# ── Ход игрока ────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("kmn:move:"))
async def kmn_move(callback: CallbackQuery, bot: Bot):
    parts   = callback.data.split(":")
    game_id = int(parts[2])
    move    = parts[3]   # rock | scissors | paper
    user_id = callback.from_user.id

    game = db.get_kmn_game(game_id)
    if not game or game["status"] not in ("waiting_move_both", "waiting_move_initiator", "waiting_move_opponent"):
        await callback.answer("Игра не активна.", show_alert=True)
        return

    is_initiator = user_id == game["initiator_id"]
    is_opponent  = user_id == game["opponent_id"]
    if not is_initiator and not is_opponent:
        await callback.answer("Это не твоя игра.", show_alert=True)
        return

    # Проверяем что этот игрок ещё не ходил
    if is_initiator and game["initiator_move"]:
        await callback.answer("Ты уже сделал ход — ждём соперника.", show_alert=True)
        return
    if is_opponent and game["opponent_move"]:
        await callback.answer("Ты уже сделал ход — ждём соперника.", show_alert=True)
        return

    # Сохраняем ход
    if is_initiator:
        db.update_kmn_game(game_id, initiator_move=move,
            status="waiting_move_opponent" if not game["opponent_move"] else game["status"])
    else:
        db.update_kmn_game(game_id, opponent_move=move,
            status="waiting_move_initiator" if not game["initiator_move"] else game["status"])

    await callback.message.edit_text(
        f"⏳ Ход принят: {MOVE_EMOJI[move]}\nЖдём соперника...",
    )
    await callback.answer(f"Ты выбрал {MOVE_EMOJI[move]}")

    # Перечитываем актуальное состояние
    game = db.get_kmn_game(game_id)

    # Если оба походили — раскрываем
    if game["initiator_move"] and game["opponent_move"]:
        await _resolve_round(bot, game_id)

# ── Разрешение раунда ─────────────────────────────────────────────────────────

async def _resolve_round(bot: Bot, game_id: int):
    game = db.get_kmn_game(game_id)
    m1   = game["initiator_move"]
    m2   = game["opponent_move"]
    winner = round_winner(m1, m2)

    i_wins = game["initiator_wins"]
    o_wins = game["opponent_wins"]

    if winner == "p1":
        i_wins += 1
        result_text = f"✊ Раунд {game['current_round']}: {MOVE_EMOJI[m1]} vs {MOVE_EMOJI[m2]} — побеждает <b>первый игрок!</b>"
    elif winner == "p2":
        o_wins += 1
        result_text = f"✌️ Раунд {game['current_round']}: {MOVE_EMOJI[m1]} vs {MOVE_EMOJI[m2]} — побеждает <b>второй игрок!</b>"
    else:
        result_text = f"🤝 Раунд {game['current_round']}: {MOVE_EMOJI[m1]} vs {MOVE_EMOJI[m2]} — <b>ничья!</b>"

    score_text = f"\n📊 Счёт: {i_wins} : {o_wins}"

    # Проверяем завершение игры
    wins_needed = game["wins_needed"]
    if i_wins >= wins_needed:
        await _finish_game(bot, game, winner_role="initiator", i_wins=i_wins, o_wins=o_wins,
                           round_text=result_text + score_text)
        return
    if o_wins >= wins_needed:
        await _finish_game(bot, game, winner_role="opponent", i_wins=i_wins, o_wins=o_wins,
                           round_text=result_text + score_text)
        return

    # Продолжаем
    new_round = game["current_round"] + 1
    db.update_kmn_game(game_id,
        initiator_wins=i_wins, opponent_wins=o_wins,
        current_round=new_round,
        initiator_move=None, opponent_move=None,
        status="waiting_move_both"
    )

    text = result_text + score_text + f"\n\n🎯 Раунд {new_round} — делай ход!"

    for uid in (game["initiator_id"], game["opponent_id"]):
        try:
            await bot.send_message(uid, text, parse_mode="HTML",
                                   reply_markup=move_kb(game_id))
        except:
            pass

    # Таймаут на новый раунд
    asyncio.create_task(_timeout_move(bot, game_id, game["initiator_id"], game["opponent_id"], TIMEOUT_SEC))

async def _finish_game(bot: Bot, game: dict, winner_role: str,
                       i_wins: int, o_wins: int, round_text: str):
    game_id     = game["id"]
    initiator_id = game["initiator_id"]
    opponent_id  = game["opponent_id"]

    if winner_role == "initiator":
        winner_id = initiator_id
        loser_id  = opponent_id
        loser_stake_fid  = game["opponent_stake_file_id"]
        loser_stake_type = game["opponent_stake_type"]
    else:
        winner_id = opponent_id
        loser_id  = initiator_id
        loser_stake_fid  = game["initiator_stake_file_id"]
        loser_stake_type = game["initiator_stake_type"]

    db.update_kmn_game(game_id,
        initiator_wins=i_wins, opponent_wins=o_wins,
        status="finished"
    )

    final_score = f"Итог: {i_wins} : {o_wins}"

    # Сообщение победителю
    try:
        await bot.send_message(
            winner_id,
            f"🏆 <b>Ты победил в КМН!</b>\n\n{round_text}\n{final_score}\n\n"
            f"Вот ставка соперника 👇",
            parse_mode="HTML"
        )
        # Отправляем ставку проигравшего победителю
        if loser_stake_type == "photo":
            await bot.send_photo(winner_id, loser_stake_fid)
        elif loser_stake_type == "video":
            await bot.send_video(winner_id, loser_stake_fid)
        elif loser_stake_type == "voice":
            await bot.send_voice(winner_id, loser_stake_fid)
    except:
        pass

    # Сообщение проигравшему
    try:
        await bot.send_message(
            loser_id,
            f"😔 <b>Ты проиграл в КМН.</b>\n\n{round_text}\n{final_score}\n\n"
            f"Твоя ставка отправлена победителю.",
            parse_mode="HTML"
        )
    except:
        pass

# ── Отправка раунда ───────────────────────────────────────────────────────────

async def _send_round(bot: Bot, game_id: int, initiator_id: int, opponent_id: int):
    game = db.get_kmn_game(game_id)
    text = (
        f"⚔️ <b>КМН началась!</b>\n\n"
        f"До {game['wins_needed']} побед. Счёт: 0 : 0\n\n"
        f"🎯 Раунд 1 — делай ход! ⏳ 60 сек"
    )
    for uid in (initiator_id, opponent_id):
        try:
            await bot.send_message(uid, text, parse_mode="HTML",
                                   reply_markup=move_kb(game_id))
        except:
            pass

    asyncio.create_task(_timeout_move(bot, game_id, initiator_id, opponent_id, TIMEOUT_SEC))

# ── Таймауты ──────────────────────────────────────────────────────────────────

async def _timeout_stake(bot: Bot, game_id: int, player_id: int, other_id: int,
                         delay: int, role: str = "initiator"):
    await asyncio.sleep(delay)
    game = db.get_kmn_game(game_id)
    if not game:
        return
    expected_status = "waiting_stake_initiator" if role == "initiator" else "waiting_stake_opponent"
    if game["status"] != expected_status:
        return  # уже прогрессировала

    db.update_kmn_game(game_id, status="cancelled")
    try:
        await bot.send_message(player_id,
            "⏰ Время вышло! Ты не загрузил ставку. Игра отменена, тебе засчитано поражение.")
    except:
        pass
    try:
        await bot.send_message(other_id,
            "⏰ Соперник не загрузил ставку вовремя. Игра отменена, тебе засчитана победа.")
    except:
        pass

async def _timeout_accept(bot: Bot, game_id: int, initiator_id: int, opponent_id: int, delay: int):
    await asyncio.sleep(delay)
    game = db.get_kmn_game(game_id)
    if not game or game["status"] != "waiting_stake_opponent":
        return
    db.update_kmn_game(game_id, status="cancelled")
    try:
        await bot.send_message(opponent_id,
            "⏰ Время на принятие вызова вышло. Игра отменена.")
    except:
        pass
    try:
        await bot.send_message(initiator_id,
            "⏰ Соперник не принял вызов вовремя. Игра отменена.")
    except:
        pass

async def _timeout_move(bot: Bot, game_id: int, initiator_id: int, opponent_id: int, delay: int):
    await asyncio.sleep(delay)
    game = db.get_kmn_game(game_id)
    if not game or game["status"] not in ("waiting_move_both", "waiting_move_initiator", "waiting_move_opponent"):
        return

    # Кто не походил — проиграл
    i_moved = bool(game["initiator_move"])
    o_moved = bool(game["opponent_move"])

    if i_moved and o_moved:
        return  # оба успели — таймаут не нужен

    if not i_moved and not o_moved:
        # Оба не ходили — отмена
        db.update_kmn_game(game_id, status="cancelled")
        for uid in (initiator_id, opponent_id):
            try:
                await bot.send_message(uid, "⏰ Оба игрока не сделали ход. Игра отменена.")
            except:
                pass
        return

    # Кто-то один не ходил
    if not i_moved:
        # Инициатор не ходил → проиграл раунд → засчитываем ход paper/scissors/rock противнику
        await _finish_game(bot, game, winner_role="opponent",
                           i_wins=game["initiator_wins"],
                           o_wins=game["wins_needed"],
                           round_text=f"⏰ Первый игрок не сделал ход вовремя.")
    else:
        await _finish_game(bot, game, winner_role="initiator",
                           i_wins=game["wins_needed"],
                           o_wins=game["opponent_wins"],
                           round_text=f"⏰ Второй игрок не сделал ход вовремя.")
