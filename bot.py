import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from config import BOT_TOKEN
from handlers import user, admin, profile, chat, premium, kmn
import database as db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

async def main():
    db.init_db()
    db.init_kmn_table()

    bot = Bot(token=BOT_TOKEN)
    dp  = Dispatcher(storage=MemoryStorage())

    # Порядок важен: admin/premium/kmn первыми
    dp.include_router(admin.router)
    dp.include_router(premium.router)
    dp.include_router(kmn.router)
    dp.include_router(profile.router)
    dp.include_router(chat.router)
    dp.include_router(user.router)

    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("🐝 Beem Bot запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
