import os
import time
import psycopg2
import psycopg2.extras
from typing import Optional, List, Dict

DATABASE_URL = os.getenv("DATABASE_URL", "")

def get_conn():
    conn = psycopg2.connect(DATABASE_URL)
    return conn

def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id     BIGINT PRIMARY KEY,
        username    TEXT,
        name        TEXT,
        age         INTEGER,
        gender      TEXT,
        interests   TEXT,
        search_gender TEXT DEFAULT 'any',
        registered  INTEGER DEFAULT 0,
        banned      INTEGER DEFAULT 0,
        ban_until   BIGINT,
        ban_reason  TEXT,
        created_at  BIGINT DEFAULT 0
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS profiles (
        id          SERIAL PRIMARY KEY,
        user_id     BIGINT,
        description TEXT,
        created_at  BIGINT,
        active      INTEGER DEFAULT 1,
        likes       INTEGER DEFAULT 0
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS profile_likes (
        id          SERIAL PRIMARY KEY,
        profile_id  INTEGER,
        liker_id    BIGINT,
        created_at  BIGINT,
        UNIQUE(profile_id, liker_id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS profile_media (
        id          SERIAL PRIMARY KEY,
        profile_id  INTEGER,
        file_id     TEXT,
        media_type  TEXT,
        created_at  BIGINT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS chats (
        id          SERIAL PRIMARY KEY,
        profile_id  INTEGER,
        sender_id   BIGINT,
        target_id   BIGINT,
        created_at  BIGINT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS messages (
        id          SERIAL PRIMARY KEY,
        chat_id     INTEGER,
        sender_id   BIGINT,
        content     TEXT,
        msg_type    TEXT DEFAULT 'text',
        file_id     TEXT,
        created_at  BIGINT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS reports (
        id          SERIAL PRIMARY KEY,
        chat_id     INTEGER,
        reporter_id BIGINT,
        reported_id BIGINT,
        reason      TEXT,
        status      TEXT DEFAULT 'new',
        created_at  BIGINT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS blocks (
        id          SERIAL PRIMARY KEY,
        blocker_id  BIGINT,
        blocked_id  BIGINT,
        created_at  BIGINT,
        UNIQUE(blocker_id, blocked_id)
    )""")

    conn.commit()
    conn.close()

def _row(cursor, one=True):
    cols = [d[0] for d in cursor.description]
    if one:
        row = cursor.fetchone()
        return dict(zip(cols, row)) if row else None
    return [dict(zip(cols, r)) for r in cursor.fetchall()]

# ── Users ──────────────────────────────────────────────────────────────────────

def get_user(user_id: int) -> Optional[Dict]:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=%s", (user_id,))
    result = _row(c)
    conn.close()
    return result

def upsert_user(user_id: int, **kwargs):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE user_id=%s", (user_id,))
    existing = c.fetchone()
    if existing:
        sets = ", ".join(f"{k}=%s" for k in kwargs)
        c.execute(f"UPDATE users SET {sets} WHERE user_id=%s", list(kwargs.values()) + [user_id])
    else:
        kwargs["user_id"] = user_id
        cols = ", ".join(kwargs.keys())
        qs = ", ".join(["%s"] * len(kwargs))
        c.execute(f"INSERT INTO users ({cols}) VALUES ({qs})", list(kwargs.values()))
    conn.commit()
    conn.close()

def get_all_users() -> List[Dict]:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE registered=1 ORDER BY created_at DESC")
    result = _row(c, one=False)
    conn.close()
    return result

def is_banned(user_id: int) -> bool:
    user = get_user(user_id)
    if not user or not user.get("banned"):
        return False
    ban_until = user.get("ban_until")
    if ban_until is None:
        return True
    if time.time() < ban_until:
        return True
    upsert_user(user_id, banned=0, ban_until=None, ban_reason=None)
    return False

def ban_user(user_id: int, duration_key: str, reason: str = ""):
    from config import BAN_DURATIONS
    _, seconds = BAN_DURATIONS[duration_key]
    ban_until = int(time.time() + seconds) if seconds else None
    upsert_user(user_id, banned=1, ban_until=ban_until, ban_reason=reason)

def unban_user(user_id: int):
    upsert_user(user_id, banned=0, ban_until=None, ban_reason=None)

# ── Profiles ───────────────────────────────────────────────────────────────────

def create_profile(user_id: int, description: str) -> int:
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE profiles SET active=0 WHERE user_id=%s", (user_id,))
    c.execute(
        "INSERT INTO profiles (user_id, description, created_at, active) VALUES (%s,%s,%s,1) RETURNING id",
        (user_id, description, int(time.time()))
    )
    pid = c.fetchone()[0]
    conn.commit()
    conn.close()
    return pid

def add_profile_media(profile_id: int, file_id: str, media_type: str):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO profile_media (profile_id, file_id, media_type, created_at) VALUES (%s,%s,%s,%s)",
        (profile_id, file_id, media_type, int(time.time()))
    )
    conn.commit()
    conn.close()

def get_profile_media(profile_id: int) -> List[Dict]:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM profile_media WHERE profile_id=%s ORDER BY id", (profile_id,))
    result = _row(c, one=False)
    conn.close()
    return result

def get_active_profile(user_id: int) -> Optional[Dict]:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM profiles WHERE user_id=%s AND active=1", (user_id,))
    result = _row(c)
    conn.close()
    return result

def delete_active_profile(user_id: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE profiles SET active=0 WHERE user_id=%s AND active=1", (user_id,))
    conn.commit()
    conn.close()

def get_last_profile_time(user_id: int) -> int:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT MAX(created_at) as t FROM profiles WHERE user_id=%s", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] or 0 if row else 0

def get_matching_profiles(viewer_id: int, interests: List[str], limit: int = 2) -> List[Dict]:
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT p.*, u.name, u.age, u.gender, u.interests
        FROM profiles p
        JOIN users u ON p.user_id = u.user_id
        WHERE p.active=1
          AND p.user_id != %s
          AND u.banned = 0
          AND p.user_id NOT IN (SELECT blocked_id FROM blocks WHERE blocker_id=%s)
          AND p.user_id NOT IN (SELECT blocker_id FROM blocks WHERE blocked_id=%s)
        ORDER BY RANDOM()
        LIMIT 50
    """, (viewer_id, viewer_id, viewer_id))
    rows = _row(c, one=False)
    conn.close()

    results, seen = [], set()
    for d in rows:
        if d["user_id"] in seen:
            continue
        p_interests = set((d.get("interests") or "").split(","))
        if set(interests) & p_interests:
            seen.add(d["user_id"])
            results.append(d)
        if len(results) >= limit:
            break
    return results

def like_profile(profile_id: int, liker_id: int) -> bool:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id FROM profile_likes WHERE profile_id=%s AND liker_id=%s", (profile_id, liker_id))
    existing = c.fetchone()
    if existing:
        c.execute("DELETE FROM profile_likes WHERE profile_id=%s AND liker_id=%s", (profile_id, liker_id))
        c.execute("UPDATE profiles SET likes = GREATEST(0, likes-1) WHERE id=%s", (profile_id,))
        conn.commit()
        conn.close()
        return False
    else:
        c.execute(
            "INSERT INTO profile_likes (profile_id, liker_id, created_at) VALUES (%s,%s,%s)",
            (profile_id, liker_id, int(time.time()))
        )
        c.execute("UPDATE profiles SET likes = likes+1 WHERE id=%s", (profile_id,))
        conn.commit()
        conn.close()
        return True

def get_active_profiles_admin() -> List[Dict]:
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT p.*, u.name, u.age, u.gender, u.username
        FROM profiles p JOIN users u ON p.user_id = u.user_id
        WHERE p.active=1 ORDER BY p.created_at DESC
    """)
    result = _row(c, one=False)
    conn.close()
    return result

# ── Chats ──────────────────────────────────────────────────────────────────────

def create_chat(profile_id: int, sender_id: int, target_id: int) -> int:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id FROM chats WHERE profile_id=%s AND sender_id=%s", (profile_id, sender_id))
    existing = c.fetchone()
    if existing:
        conn.close()
        return existing[0]
    c.execute(
        "INSERT INTO chats (profile_id, sender_id, target_id, created_at) VALUES (%s,%s,%s,%s) RETURNING id",
        (profile_id, sender_id, target_id, int(time.time()))
    )
    cid = c.fetchone()[0]
    conn.commit()
    conn.close()
    return cid

def get_chat(chat_id: int) -> Optional[Dict]:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM chats WHERE id=%s", (chat_id,))
    result = _row(c)
    conn.close()
    return result

def get_user_chats(user_id: int) -> List[Dict]:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM chats WHERE sender_id=%s OR target_id=%s ORDER BY id DESC", (user_id, user_id))
    result = _row(c, one=False)
    conn.close()
    return result

def add_message(chat_id: int, sender_id: int, content: str, msg_type: str = "text", file_id: str = None) -> int:
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO messages (chat_id, sender_id, content, msg_type, file_id, created_at) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
        (chat_id, sender_id, content, msg_type, file_id, int(time.time()))
    )
    mid = c.fetchone()[0]
    conn.commit()
    conn.close()
    return mid

def get_chat_messages(chat_id: int, limit: int = 100) -> List[Dict]:
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "SELECT * FROM (SELECT * FROM messages WHERE chat_id=%s ORDER BY created_at DESC LIMIT %s) sub ORDER BY created_at ASC",
        (chat_id, limit)
    )
    result = _row(c, one=False)
    conn.close()
    return result

def get_all_chats_admin() -> List[Dict]:
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT c.*,
               us.name as sender_name, us.username as sender_username,
               ut.name as target_name, ut.username as target_username,
               (SELECT COUNT(*) FROM messages m WHERE m.chat_id=c.id) as msg_count,
               (SELECT content FROM messages m WHERE m.chat_id=c.id ORDER BY created_at DESC LIMIT 1) as last_msg
        FROM chats c
        LEFT JOIN users us ON c.sender_id = us.user_id
        LEFT JOIN users ut ON c.target_id = ut.user_id
        ORDER BY c.created_at DESC
    """)
    result = _row(c, one=False)
    conn.close()
    return result

# ── Reports ────────────────────────────────────────────────────────────────────

def add_report(chat_id: int, reporter_id: int, reported_id: int, reason: str = ""):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO reports (chat_id, reporter_id, reported_id, reason, created_at) VALUES (%s,%s,%s,%s,%s)",
        (chat_id, reporter_id, reported_id, reason, int(time.time()))
    )
    conn.commit()
    conn.close()

def get_reports(status: str = None) -> List[Dict]:
    conn = get_conn()
    c = conn.cursor()
    if status:
        c.execute("""
            SELECT r.*, u.name as reported_name, u.username as reported_username
            FROM reports r LEFT JOIN users u ON r.reported_id = u.user_id
            WHERE r.status=%s ORDER BY r.created_at DESC
        """, (status,))
    else:
        c.execute("""
            SELECT r.*, u.name as reported_name, u.username as reported_username
            FROM reports r LEFT JOIN users u ON r.reported_id = u.user_id
            ORDER BY r.created_at DESC
        """)
    result = _row(c, one=False)
    conn.close()
    return result

def resolve_report(report_id: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE reports SET status='resolved' WHERE id=%s", (report_id,))
    conn.commit()
    conn.close()

# ── Blocks ─────────────────────────────────────────────────────────────────────

def block_user(blocker_id: int, blocked_id: int):
    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute(
            "INSERT INTO blocks (blocker_id, blocked_id, created_at) VALUES (%s,%s,%s)",
            (blocker_id, blocked_id, int(time.time()))
        )
        conn.commit()
    except Exception:
        conn.rollback()
    conn.close()

def is_blocked(blocker_id: int, blocked_id: int) -> bool:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id FROM blocks WHERE blocker_id=%s AND blocked_id=%s", (blocker_id, blocked_id))
    row = c.fetchone()
    conn.close()
    return row is not None
