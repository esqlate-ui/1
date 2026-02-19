from flask import Flask, render_template, request, redirect, session, url_for, jsonify, abort, Response
import database as db
import time
import os
import requests as req
from config import ADMIN_PASSWORD, ADMIN_SECRET, INTERESTS_DISPLAY, BAN_DURATIONS, BOT_TOKEN

app = Flask(__name__)
app.secret_key = ADMIN_SECRET

GENDER_MAP = {"male": "Парень", "female": "Девушка", "other": "Другое"}
SGENDER_MAP = {"male": "Парней", "female": "Девушек", "any": "Всех"}

def fmt_time(ts):
    if not ts: return "—"
    return time.strftime("%d.%m.%Y %H:%M", time.localtime(ts))

def fmt_interests(s):
    if not s: return "—"
    return ", ".join(INTERESTS_DISPLAY.get(i, i) for i in s.split(",") if i)

def require_login(f):
    from functools import wraps
    @wraps(f)
    def wrap(*a, **kw):
        if not session.get("admin"): return redirect(url_for("login"))
        return f(*a, **kw)
    return wrap

# ── Auth ───────────────────────────────────────────────────────────────────────

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["admin"] = True
            return redirect(url_for("dashboard"))
        error = "Неверный пароль"
    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ── Dashboard ──────────────────────────────────────────────────────────────────

@app.route("/")
@require_login
def dashboard():
    users = db.get_all_users()
    chats = db.get_all_chats_admin()
    profiles = db.get_active_profiles_admin()
    reports = db.get_reports("new")
    conn = db.get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM messages")
    msg_count = c.fetchone()[0]
    conn.close()
    return render_template("dashboard.html",
        users_count=len(users), chats_count=len(chats),
        profiles_count=len(profiles), reports_count=len(reports),
        messages_count=msg_count
    )

@app.route("/api/stats")
@require_login
def api_stats():
    users = db.get_all_users()
    chats = db.get_all_chats_admin()
    profiles = db.get_active_profiles_admin()
    reports = db.get_reports("new")
    conn = db.get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM messages")
    msg_count = c.fetchone()[0]
    conn.close()
    return jsonify(users=len(users), chats=len(chats),
                   profiles=len(profiles), reports=len(reports), messages=msg_count)

# ── Users ──────────────────────────────────────────────────────────────────────

@app.route("/users")
@require_login
def users():
    all_users = db.get_all_users()
    for u in all_users:
        u["gender_display"] = GENDER_MAP.get(u.get("gender"), "—")
        u["interests_display"] = fmt_interests(u.get("interests"))
        u["created_display"] = fmt_time(u.get("created_at"))
        u["ban_display"] = "🔒 Забанен" if u.get("banned") else "✅ Активен"
        u["ban_until_display"] = fmt_time(u.get("ban_until")) if u.get("ban_until") else "—"
    return render_template("users.html", users=all_users)

@app.route("/user/<int:user_id>")
@require_login
def user_detail(user_id):
    u = db.get_user(user_id)
    if not u: abort(404)
    u["gender_display"] = GENDER_MAP.get(u.get("gender"), "—")
    u["interests_display"] = fmt_interests(u.get("interests"))
    u["created_display"] = fmt_time(u.get("created_at"))
    u["ban_until_display"] = fmt_time(u.get("ban_until")) if u.get("ban_until") else "Навсегда"
    chats = db.get_user_chats(user_id)
    profile = db.get_active_profile(user_id)
    return render_template("user_detail.html", u=u, chats=chats, profile=profile,
                           ban_durations=BAN_DURATIONS, fmt_time=fmt_time)

@app.route("/user/<int:user_id>/ban", methods=["POST"])
@require_login
def ban_user(user_id):
    duration = request.form.get("duration", "24h")
    reason = request.form.get("reason", "Нарушение правил")
    db.ban_user(user_id, duration, reason)
    db.delete_active_profile(user_id)
    return redirect(url_for("user_detail", user_id=user_id))

@app.route("/user/<int:user_id>/unban", methods=["POST"])
@require_login
def unban_user(user_id):
    db.unban_user(user_id)
    return redirect(url_for("user_detail", user_id=user_id))

# ── Profiles ───────────────────────────────────────────────────────────────────

@app.route("/profiles")
@require_login
def profiles():
    all_profiles = db.get_active_profiles_admin()
    for p in all_profiles:
        p["interests_display"] = fmt_interests(p.get("interests"))
        p["created_display"] = fmt_time(p.get("created_at"))
        p["gender_display"] = GENDER_MAP.get(p.get("gender"), "—")
        p["media"] = db.get_profile_media(p["id"])
    return render_template("profiles.html", profiles=all_profiles)

# ── Chats ──────────────────────────────────────────────────────────────────────

@app.route("/chats")
@require_login
def chats():
    all_chats = db.get_all_chats_admin()
    for c in all_chats:
        c["created_display"] = fmt_time(c.get("created_at"))
    return render_template("chats.html", chats=all_chats)

@app.route("/chat/<int:chat_id>")
@require_login
def chat_detail(chat_id):
    chat = db.get_chat(chat_id)
    if not chat: abort(404)
    messages = db.get_chat_messages(chat_id, limit=500)
    sender = db.get_user(chat["sender_id"])
    target = db.get_user(chat["target_id"])
    for m in messages:
        m["time_display"] = fmt_time(m.get("created_at"))
        m["is_sender"] = m["sender_id"] == chat["sender_id"]
    return render_template("chat_detail.html",
        chat=chat, messages=messages,
        sender=sender, target=target,
        sender_name=sender["name"] if sender else f"ID:{chat['sender_id']}",
        target_name=target["name"] if target else f"ID:{chat['target_id']}"
    )

# ── Reports ────────────────────────────────────────────────────────────────────

@app.route("/reports")
@require_login
def reports():
    all_reports = db.get_reports()
    for r in all_reports:
        r["created_display"] = fmt_time(r.get("created_at"))
    return render_template("reports.html", reports=all_reports)

@app.route("/report/<int:report_id>/resolve", methods=["POST"])
@require_login
def resolve_report(report_id):
    db.resolve_report(report_id)
    return redirect(url_for("reports"))

# ── Telegram Media Proxy ───────────────────────────────────────────────────────

@app.route("/media/<file_id>")
@require_login
def media_proxy(file_id):
    """Проксирует медиафайлы из Telegram"""
    try:
        # Получаем file_path через Bot API
        r = req.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={file_id}", timeout=10)
        data = r.json()
        if not data.get("ok"):
            return "File not found", 404
        file_path = data["result"]["file_path"]
        # Скачиваем файл
        file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
        file_r = req.get(file_url, timeout=30, stream=True)
        content_type = file_r.headers.get("Content-Type", "application/octet-stream")
        return Response(file_r.iter_content(chunk_size=8192), content_type=content_type)
    except Exception as e:
        return f"Error: {e}", 500

def run_web():
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
