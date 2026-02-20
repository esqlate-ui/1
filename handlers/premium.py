import time
from aiogram import Router, F, Bot
from aiogram.types import (
    Message, CallbackQuery,
    LabeledPrice, PreCheckoutQuery
)
from aiogram.filters import Command

import database as db
from config import PREMIUM_PLANS, TON_WALLET, ADMIN_IDS
from keyboards import main_kb, premium_plans_kb, premium_pay_kb

router = Router()

def _prem_status_text(user_id: int) -> str:
    user = db.get_user(user_id)
    if not user:
        return ""
    if db.is_premium(user_id):
        until = user.get("premium_until")
        if until is None:
            exp = "♾️ Бессрочно"
        else:
            exp = f"до {time.strftime('%d.%m.%Y', time.localtime(until))}"
        return f"✅ У тебя активен <b>👑 Premium</b> ({exp})\n\n"
    return ""

# ── Страница Premium ──────────────────────────────────────────────────────────

@router.message(F.text == "👑 Premium")
async def premium_page(message: Message):
    status = _prem_status_text(message.from_user.id)
    await message.answer(
        f"{status}"
        f"<b>👑 Beem Premium</b>\n\n"
        f"Что даёт Premium:\n"
        f"• 👥 5 анкет за один просмотр (вместо 2)\n"
        f"• 🚀 Приоритет показа твоей анкеты\n"
        f"• 🔍 Фильтры: пол, возраст, только с фото/видео\n"
        f"• 📸 Фото и видео в анкете\n"
        f"• 👑 Бейдж в анкете и уведомлениях\n"
        f"• ⏱ Без кулдауна на создание анкеты\n\n"
        f"Выбери тариф:",
        parse_mode="HTML",
        reply_markup=premium_plans_kb()
    )

# ── Выбор тарифа ──────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("prem:choose:"))
async def prem_choose(callback: CallbackQuery):
    plan_key = callback.data.split(":")[2]
    if plan_key not in PREMIUM_PLANS:
        await callback.answer("Тариф не найден", show_alert=True)
        return
    p = PREMIUM_PLANS[plan_key]
    await callback.message.edit_text(
        f"<b>{p['label']}</b> — {p['desc']}\n\n"
        f"Выбери способ оплаты:",
        parse_mode="HTML",
        reply_markup=premium_pay_kb(plan_key)
    )
    await callback.answer()

@router.callback_query(F.data == "prem:back")
async def prem_back(callback: CallbackQuery):
    status = _prem_status_text(callback.from_user.id)
    await callback.message.edit_text(
        f"{status}"
        f"<b>👑 Beem Premium</b>\n\n"
        f"Что даёт Premium:\n"
        f"• 👥 5 анкет за один просмотр (вместо 2)\n"
        f"• 🚀 Приоритет показа твоей анкеты\n"
        f"• 🔍 Фильтры: пол, возраст, только с фото/видео\n"
        f"• 📸 Фото и видео в анкете\n"
        f"• 👑 Бейдж в анкете и уведомлениях\n"
        f"• ⏱ Без кулдауна на создание анкеты\n\n"
        f"Выбери тариф:",
        parse_mode="HTML",
        reply_markup=premium_plans_kb()
    )
    await callback.answer()

# ── Оплата Stars ──────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("prem:pay_stars:"))
async def prem_pay_stars(callback: CallbackQuery, bot: Bot):
    plan_key = callback.data.split(":")[2]
    if plan_key not in PREMIUM_PLANS:
        await callback.answer("Тариф не найден", show_alert=True)
        return
    p = PREMIUM_PLANS[plan_key]
    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title=f"👑 Beem Premium — {p['label']}",
        description=p["desc"],
        payload=f"premium:{plan_key}",
        currency="XTR",           # Telegram Stars
        prices=[LabeledPrice(label=p["label"], amount=p["stars"])],
        provider_token="",        # для Stars всегда пустой
    )
    await callback.answer()

@router.pre_checkout_query()
async def pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await pre_checkout_query.answer(ok=True)

@router.message(F.successful_payment)
async def successful_payment(message: Message):
    payload  = message.successful_payment.invoice_payload  # "premium:week"
    parts    = payload.split(":")
    if len(parts) != 2 or parts[0] != "premium":
        return
    plan_key = parts[1]
    if plan_key not in PREMIUM_PLANS:
        return

    p    = PREMIUM_PLANS[plan_key]
    days = p["days"]
    db.give_premium(message.from_user.id, days)
    db.add_payment(message.from_user.id, plan_key, "stars", str(p["stars"]))

    if days is None:
        exp_txt = "♾️ Бессрочно"
    else:
        exp_txt = f"до {time.strftime('%d.%m.%Y', time.localtime(time.time() + days * 86400))}"

    profile = db.get_active_profile(message.from_user.id)
    await message.answer(
        f"🎉 <b>👑 Premium активирован!</b>\n\n"
        f"Тариф: {p['label']}\n"
        f"Действует: {exp_txt}\n\n"
        f"Теперь тебе доступны все возможности Premium!",
        parse_mode="HTML",
        reply_markup=main_kb(bool(profile))
    )

    # Уведомить всех админов
    user = db.get_user(message.from_user.id)
    for admin_id in ADMIN_IDS:
        try:
            await message.bot.send_message(
                admin_id,
                f"💰 Новая оплата Stars!\n"
                f"👤 {user['name'] if user else 'Unknown'} (ID:{message.from_user.id})\n"
                f"Тариф: {p['label']} — {p['stars']}⭐"
            )
        except:
            pass

# ── Оплата TON ────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("prem:pay_ton:"))
async def prem_pay_ton(callback: CallbackQuery):
    plan_key = callback.data.split(":")[2]
    if plan_key not in PREMIUM_PLANS:
        await callback.answer("Тариф не найден", show_alert=True)
        return
    p = PREMIUM_PLANS[plan_key]

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    await callback.message.answer(
        f"💎 <b>Оплата TON — {p['label']}</b>\n\n"
        f"Сумма: <b>{p['ton']} TON</b>\n\n"
        f"Адрес кошелька:\n<code>{TON_WALLET}</code>\n\n"
        f"Комментарий к переводу (обязательно!):\n<code>{callback.from_user.id}</code>\n\n"
        f"После перевода нажми кнопку ниже 👇",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="✅ Я оплатил, уведомить администратора",
                callback_data=f"prem:ton_notify:{plan_key}"
            )]
        ])
    )
    await callback.answer()

@router.callback_query(F.data.startswith("prem:ton_notify:"))
async def ton_notify_admin(callback: CallbackQuery, bot: Bot):
    plan_key = callback.data.split(":")[2]
    p        = PREMIUM_PLANS.get(plan_key, {})
    user     = db.get_user(callback.from_user.id)

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"💎 <b>Запрос на активацию TON Premium</b>\n\n"
                f"👤 {user['name'] if user else 'Unknown'} (@{user.get('username') or '—'})\n"
                f"ID: <code>{callback.from_user.id}</code>\n"
                f"Тариф: {p.get('label','?')} — {p.get('ton','?')} TON\n\n"
                f"Проверь транзакцию и активируй:",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text=f"✅ Выдать Premium ({p.get('label','?')})",
                        callback_data=f"adm:giveprem_plan:{callback.from_user.id}:{plan_key}"
                    )]
                ])
            )
        except:
            pass

    await callback.message.edit_text(
        "✅ Администратор уведомлён! Как только платёж подтвердится — Premium будет активирован.\n\n"
        "Обычно это занимает до 30 минут."
    )
    await callback.answer()

# ── Ручная выдача Premium (команда для админа) ────────────────────────────────

@router.message(Command("givepremium"))
async def cmd_give_premium(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    parts = message.text.strip().split()
    if len(parts) < 2:
        await message.answer("Использование: /givepremium <user_id> [план: week/month/forever]\nПример: /givepremium 123456789 month")
        return

    try:
        target_id = int(parts[1])
    except ValueError:
        await message.answer("Неверный user_id")
        return

    plan_key = parts[2] if len(parts) > 2 else "month"
    if plan_key not in PREMIUM_PLANS:
        await message.answer(f"Неверный план. Доступны: {', '.join(PREMIUM_PLANS.keys())}")
        return

    p    = PREMIUM_PLANS[plan_key]
    days = p["days"]
    db.give_premium(target_id, days)
    db.add_payment(target_id, plan_key, "manual", "0")

    target = db.get_user(target_id)
    await message.answer(
        f"✅ Premium выдан!\n"
        f"👤 {target['name'] if target else target_id}\n"
        f"Тариф: {p['label']}"
    )

    try:
        profile = db.get_active_profile(target_id)
        exp_txt = "♾️ Бессрочно" if days is None else f"до {time.strftime('%d.%m.%Y', time.localtime(time.time() + days * 86400))}"
        await message.bot.send_message(
            target_id,
            f"🎉 <b>👑 Premium активирован администратором!</b>\n\n"
            f"Тариф: {p['label']}\n"
            f"Действует: {exp_txt}",
            parse_mode="HTML",
            reply_markup=main_kb(bool(profile))
        )
    except:
        pass

# ── Выдача Premium из кнопки в чате с админом ────────────────────────────────

@router.callback_query(F.data.startswith("adm:giveprem_plan:"))
async def adm_giveprem_plan(callback: CallbackQuery, bot: Bot):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа", show_alert=True)
        return
    parts = callback.data.split(":")
    # формат: adm:giveprem_plan:USER_ID:PLAN_KEY
    target_id_str = parts[2]
    plan_key      = parts[3]
    target_id = int(target_id_str)
    if plan_key not in PREMIUM_PLANS:
        await callback.answer("Неверный план", show_alert=True)
        return

    p    = PREMIUM_PLANS[plan_key]
    days = p["days"]
    db.give_premium(target_id, days)
    db.add_payment(target_id, plan_key, "ton", str(p["ton"]))

    await callback.message.edit_text(f"✅ Premium ({p['label']}) выдан пользователю {target_id}")
    await callback.answer("✅ Выдано!")

    try:
        profile = db.get_active_profile(target_id)
        exp_txt = "♾️ Бессрочно" if days is None else f"до {time.strftime('%d.%m.%Y', time.localtime(time.time() + days * 86400))}"
        await bot.send_message(
            target_id,
            f"🎉 <b>👑 Premium активирован!</b>\n\n"
            f"Тариф: {p['label']}\n"
            f"Действует: {exp_txt}",
            parse_mode="HTML",
            reply_markup=main_kb(bool(profile))
        )
    except:
        pass

# ── Выдача Premium кнопкой из карточки пользователя в боте-админке ───────────

@router.callback_query(F.data.startswith("adm:giveprem:"))
async def adm_giveprem_choose(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа", show_alert=True)
        return
    target_id = int(callback.data.split(":")[2])
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    rows = []
    for key, p in PREMIUM_PLANS.items():
        rows.append([InlineKeyboardButton(
            text=p["label"],
            callback_data=f"adm:giveprem_plan:{target_id}:{key}"
        )])
    await callback.message.answer(
        f"Выбери тариф для пользователя {target_id}:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
    )
    await callback.answer()
