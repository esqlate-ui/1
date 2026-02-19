import threading
import logging
import database as db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# Init DB
db.init_db()
logging.info("✅ База данных инициализирована")

# Run web panel in background thread
def start_web():
    from web import run_web
    run_web()

t = threading.Thread(target=start_web, daemon=True)
t.start()
logging.info("✅ Веб-панель запущена на порту 5000")

# Run bot (blocking)
logging.info("✅ Запуск бота...")
import subprocess
subprocess.run(["python", "bot.py"])
