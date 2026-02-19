from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import CommandStart

import database as db
from config import INTERESTS_DISPLAY
from keyboards import main_kb, gender_kb, interests_kb, settings_kb

router = Router()

GENDER_MAP = {"male": "👦 Парень", "female": "👧 Девушка", "other": "⚧ Другое"}

def fmt_interests(interests_str: str) -> str:
    if not interests_str:
        return "—"
    return ", ".join(INTERESTS_DISPLAY.get(i, i) for i in interests_str.split(",") if i)

# ── FSM ────────────────────────────────────────────────────────────────────────

class Reg(StatesGroup):
    name = State()
    age = State()
    gender = State()
    interests = State()

class Sett(StatesGroup):
    name = State()
    age = State()
    gender = State()
    interests = State()

# ── Start ──────────────────────────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    if db.is_banned(message.from_user.id):
        user = db.get_user(message.from_user.id)
        reason = user.get("ban_reason") or "нарушение правил"
        await message.answer(f"🚫 Ты заблокирован.\nПричина: {reason}")
        return
    user = db.get_user(message.from_user.id)
    if user and user.get("registered"):
        profile = db.get_active_profile(message.from_user.id)
        await message.answer(
            "👋 С возвращением в <b>Beem</b>!\n\nВыбери действие:",
            parse_mode="HTML",
            reply_markup=main_kb(has_profile=bool(profile))
        )
    else:
        await message.answer(
            "🐝 Добро пожаловать в <b>Beem</b>!\n\n"
            "Анонимные знакомства — общайся, флиртуй, находи своих.\n\n"
            "Давай настроим профиль. Как тебя зовут?",
            parse_mode="HTML"
        )
        await state.set_state(Reg.name)

@router.message(Reg.name)
async def reg_name(message: Message, state: FSMContext):
    name = message.text.strip()[:30]
    if len(name) < 2:
        await message.answer("Имя должно быть от 2 символов:")
        return
    await state.update_data(name=name)
    await message.answer(f"Отлично, {name}! Сколько тебе лет?")
    await state.set_state(Reg.age)

@router.message(Reg.age)
async def reg_age(message: Message, state: FSMContext):
    try:
        age = int(message.text.strip())
        assert 10 <= age <= 99
    except:
        await message.answer("Введи возраст числом (10–99):")
        return
    await state.update_data(age=age)
    await message.answer("Твой пол:", reply_markup=gender_kb("regender"))
    await state.set_state(Reg.gender)

@router.callback_query(Reg.gender, F.data.startswith("regender:"))
async def reg_gender(callback: CallbackQuery, state: FSMContext):
    gender = callback.data.split(":")[1]
    await state.update_data(gender=gender, interests=[])
    await callback.message.edit_text("Выбери интересы (хотя бы один):", reply_markup=interests_kb([]))
    await state.set_state(Reg.interests)

@router.callback_query(Reg.interests, F.data.startswith("interest:"))
async def reg_interests(callback: CallbackQuery, state: FSMContext):
    key = callback.data.split(":")[1]
    data = await state.get_data()
    selected = data.get("interests", [])
    if key == "done":
        if not selected:
            await callback.answer("Выбери хотя бы один интерес!", show_alert=True)
            return
        db.upsert_user(
            callback.from_user.id,
            username=callback.from_user.username or "",
            name=data["name"], age=data["age"],
            gender=data["gender"], interests=",".join(selected),
            registered=1, created_at=__import__("time").time()
        )
        await state.clear()
        await callback.message.edit_text(
            f"✅ Профиль создан!\n\n"
            f"👤 <b>{data['name']}</b>, {data['age']} лет\n"
            f"Пол: {GENDER_MAP.get(data['gender'])}\n"
            f"Интересы: {fmt_interests(','.join(selected))}",
            parse_mode="HTML"
        )
        await callback.message.answer(
            "Теперь можешь добавить анкету и смотреть других!",
            reply_markup=main_kb(has_profile=False)
        )
    else:
        if key in selected: selected.remove(key)
        else: selected.append(key)
        await state.update_data(interests=selected)
        await callback.message.edit_reply_markup(reply_markup=interests_kb(selected))
    await callback.answer()

# ── Settings ───────────────────────────────────────────────────────────────────

@router.message(F.text == "⚙️ Настройки")
async def cmd_settings(message: Message):
    user = db.get_user(message.from_user.id)
    if not user or not user.get("registered"):
        await message.answer("Сначала пройди регистрацию: /start")
        return
    interests = fmt_interests(user.get("interests", ""))
    await message.answer(
        f"⚙️ <b>Твой профиль</b>\n\n"
        f"👤 Имя: {user['name']}\n"
        f"🎂 Возраст: {user['age']}\n"
        f"⚧ Пол: {GENDER_MAP.get(user.get('gender'), '—')}\n"
        f"🎯 Интересы: {interests}\n\n"
        f"Что хочешь изменить?",
        parse_mode="HTML",
        reply_markup=settings_kb()
    )

@router.callback_query(F.data.startswith("set:"))
async def settings_action(callback: CallbackQuery, state: FSMContext):
    action = callback.data.split(":")[1]
    if action == "name":
        await callback.message.answer("Введи новое имя:")
        await state.set_state(Sett.name)
    elif action == "age":
        await callback.message.answer("Введи новый возраст:")
        await state.set_state(Sett.age)
    elif action == "gender":
        await callback.message.answer("Выбери пол:", reply_markup=gender_kb("setgender"))
        await state.set_state(Sett.gender)
    elif action == "interests":
        user = db.get_user(callback.from_user.id)
        sel = user.get("interests", "").split(",") if user.get("interests") else []
        await state.update_data(interests=sel)
        await callback.message.answer("Выбери интересы:", reply_markup=interests_kb(sel))
        await state.set_state(Sett.interests)
    await callback.answer()

@router.message(Sett.name)
async def sett_name(message: Message, state: FSMContext):
    name = message.text.strip()[:30]
    if len(name) < 2:
        await message.answer("Слишком коротко:")
        return
    db.upsert_user(message.from_user.id, name=name)
    await state.clear()
    profile = db.get_active_profile(message.from_user.id)
    await message.answer(f"✅ Имя изменено: <b>{name}</b>", parse_mode="HTML", reply_markup=main_kb(bool(profile)))

@router.message(Sett.age)
async def sett_age(message: Message, state: FSMContext):
    try:
        age = int(message.text.strip())
        assert 10 <= age <= 99
    except:
        await message.answer("Введи возраст (10–99):")
        return
    db.upsert_user(message.from_user.id, age=age)
    await state.clear()
    profile = db.get_active_profile(message.from_user.id)
    await message.answer(f"✅ Возраст изменён: {age}", reply_markup=main_kb(bool(profile)))

@router.callback_query(Sett.gender, F.data.startswith("setgender:"))
async def sett_gender(callback: CallbackQuery, state: FSMContext):
    gender = callback.data.split(":")[1]
    db.upsert_user(callback.from_user.id, gender=gender)
    await state.clear()
    profile = db.get_active_profile(callback.from_user.id)
    await callback.message.answer("✅ Пол обновлён!", reply_markup=main_kb(bool(profile)))
    await callback.answer()

@router.callback_query(Sett.interests, F.data.startswith("interest:"))
async def sett_interests(callback: CallbackQuery, state: FSMContext):
    key = callback.data.split(":")[1]
    data = await state.get_data()
    selected = data.get("interests", [])
    if key == "done":
        if not selected:
            await callback.answer("Выбери хотя бы один!", show_alert=True)
            return
        db.upsert_user(callback.from_user.id, interests=",".join(selected))
        await state.clear()
        profile = db.get_active_profile(callback.from_user.id)
        await callback.message.answer("✅ Интересы обновлены!", reply_markup=main_kb(bool(profile)))
    else:
        if key in selected: selected.remove(key)
        else: selected.append(key)
        await state.update_data(interests=selected)
        await callback.message.edit_reply_markup(reply_markup=interests_kb(selected))
    await callback.answer()

@router.callback_query(F.data == "cancel")
async def cancel_action(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    await callback.answer()
