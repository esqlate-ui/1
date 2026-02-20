import os
import time
import psycopg2
import psycopg2.extras
from typing import Optional, List, Dict

DATABASE_URL = os.getenv("DATABASE_URL", "")

# Разрешённые колонки для upsert_user (защита от SQL-инъекций)
_ALLOWED_USER_COLS = {
    "username", "name", "age", "gender", "interests",
    "search_gender", "search_age_min", "search_age_max",
    "search_media_only", "registered", "banned", "ban_until",
    "ban_reason", "created_at", "premium", "premium_until",
}

def get_conn():
    conn = psycopg2.connect(DATABASE_URL)
    return conn

def init_db():
    conn = get_conn()
    c = conn.cursor()

    # Users
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id          BIGINT PRIMARY KEY,
        username         TEXT,
        name             TEXT,
        age              INTEGER,
        gender           TEXT,
        interests        TEXT,
        search_gender    TEXT DEFAULT 'any',
        search_age_min   INTEGER DEFAULT 0,
        search_age_max   INTEGER DEFAULT 99,
        search_media_only INTEGER DEFAULT 0,
        registered       INTEGER DEFAULT 0,
        banned           INTEGER DEFAULT 0,
        ban_until        BIGINT,
        ban_reason       TEXT,
        created_at       BIGINT DEFAULT 0,
        premium          INTEGER DEFAULT 0,
        premium_until    BIGINT
    )""")

    # Миграции для существующих таблиц (безопасно — IF NOT EXISTS через ALTER)
    for col, defn in [
        ("search_age_min",    "INTEGER DEFAULT 0"),
        ("search_age_max",    "INTEGER DEFAULT 99"),
        ("search_media_only", "INTEGER DEFAULT 0"),
        ("premium",           "INTEGER DEFAULT 0"),
        ("premium_until",     "BIGINT"),
    ]:
        try:
            c.execute(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col} {defn}")
        except Exception:
            conn.rollback()

    # Profiles
    c.execute("""CREATE TABLE IF NOT EXISTS profiles (
        id          SERIAL PRIMARY KEY,
        user_id     BIGINT,
        description TEXT,
        created_at  BIGINT,
        active      INTEGER DEFAULT 1
    )""")

    # Profile media
    c.execute("""CREATE TABLE IF NOT EXISTS profile_media (
        id          SERIAL PRIMARY KEY,
        profile_id  INTEGER,
        file_id     TEXT,
        media_type  TEXT,
        created_at  BIGINT
    )""")

    # Chats
    c.execute("""CREATE TABLE IF NOT EXISTS chats (
        id          SERIAL PRIMARY KEY,
        profile_id  INTEGER,
        sender_id   BIGINT,
        target_id   BIGINT,
        created_at  BIGINT,
        closed      INTEGER DEFAULT 0
    )""")
    try:
        c.execute("ALTER TABLE chats ADD COLUMN IF NOT EXISTS closed INTEGER DEFAULT 0")
    except Exception:
        conn.rollback()

    # Messages
    c.execute("""CREATE TABLE IF NOT EXISTS messages (
        id          SERIAL PRIMARY KEY,
        chat_id     INTEGER,
        sender_id   BIGINT,
        content     TEXT,
        msg_type    TEXT DEFAULT 'text',
        file_id     TEXT,
        created_at  BIGINT,
        read        INTEGER DEFAULT 0
    )""")
    try:
        c.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS read INTEGER DEFAULT 0")
    except Exception:
        conn.rollback()

    # Reports
    c.execute("""CREATE TABLE IF NOT EXISTS reports (
        id          SERIAL PRIMARY KEY,
        chat_id     INTEGER,
        reporter_id BIGINT,
        reported_id BIGINT,
        reason      TEXT,
        status      TEXT DEFAULT 'new',
        created_at  BIGINT
    )""")

    # Blocks
    c.execute("""CREATE TABLE IF NOT EXISTS blocks (
        id          SERIAL PRIMARY KEY,
        blocker_id  BIGINT,
        blocked_id  BIGINT,
        created_at  BIGINT,
        UNIQUE(blocker_id, blocked_id)
    )""")

    # Payments
    c.execute("""CREATE TABLE IF NOT EXISTS payments (
        id          SERIAL PRIMARY KEY,
        user_id     BIGINT,
        plan        TEXT,
        method      TEXT,
        amount      TEXT,
        created_at  BIGINT
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
    # Защита от SQL-инъекций
    bad = set(kwargs) - _ALLOWED_USER_COLS
    if bad:
        raise ValueError(f"Недопустимые колонки: {bad}")
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE user_id=%s", (user_id,))
    existing = c.fetchone()
    if existing:
        sets = ", ".join(f"{k}=%s" for k in kwargs)
        c.execute(f"UPDATE users SET {sets} WHERE user_id=%s",
                  list(kwargs.values()) + [user_id])
    else:
        kwargs["user_id"] = user_id
        cols = ", ".join(kwargs.keys())
        qs   = ", ".join(["%s"] * len(kwargs))
        c.execute(f"INSERT INTO users ({cols}) VALUES ({qs})",
                  list(kwargs.values()))
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

# ── Premium ────────────────────────────────────────────────────────────────────

def is_premium(user_id: int) -> bool:
    user = get_user(user_id)
    if not user or not user.get("premium"):
        return False
    until = user.get("premium_until")
    if until is None:
        return True   # бессрочный
    if time.time() < until:
        return True
    # истёк — сбрасываем
    upsert_user(user_id, premium=0, premium_until=None)
    return False

def give_premium(user_id: int, days: Optional[int]):
    """days=None — бессрочно"""
    if days is None:
        upsert_user(user_id, premium=1, premium_until=None)
    else:
        until = int(time.time() + days * 86400)
        upsert_user(user_id, premium=1, premium_until=until)

def add_payment(user_id: int, plan: str, method: str, amount: str):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO payments (user_id, plan, method, amount, created_at) VALUES (%s,%s,%s,%s,%s)",
        (user_id, plan, method, amount, int(time.time()))
    )
    conn.commit()
    conn.close()

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

def profile_has_media(profile_id: int) -> bool:
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "SELECT id FROM profile_media WHERE profile_id=%s AND media_type IN ('photo','video') LIMIT 1",
        (profile_id,)
    )
    row = c.fetchone()
    conn.close()
    return row is not None

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

def get_matching_profiles(viewer_id: int, interests: List[str],
                          limit: int = 2,
                          search_gender: str = "any",
                          age_min: int = 0, age_max: int = 99,
                          media_only: bool = False,
                          viewer_is_premium: bool = False) -> List[Dict]:
    conn = get_conn()
    c = conn.cursor()

    # Премиум-анкеты идут первыми (приоритет)
    c.execute("""
        SELECT p.*, u.name, u.age, u.gender, u.interests, u.premium
        FROM profiles p
        JOIN users u ON p.user_id = u.user_id
        WHERE p.active=1
          AND p.user_id != %s
          AND u.banned = 0
          AND u.age >= %s AND u.age <= %s
          AND p.user_id NOT IN (SELECT blocked_id FROM blocks WHERE blocker_id=%s)
          AND p.user_id NOT IN (SELECT blocker_id FROM blocks WHERE blocked_id=%s)
          AND p.user_id NOT IN (
              SELECT CASE WHEN c.sender_id=%s THEN c.target_id ELSE c.sender_id END
              FROM chats c
              WHERE (c.sender_id=%s OR c.target_id=%s) AND c.closed=1
          )
        ORDER BY u.premium DESC, RANDOM()
        LIMIT 100
    """, (viewer_id, age_min, age_max, viewer_id, viewer_id, viewer_id, viewer_id, viewer_id))
    rows = _row(c, one=False)
    conn.close()

    results, seen = [], set()
    for d in rows:
        if d["user_id"] in seen:
            continue
        # Фильтр по полу
        if search_gender != "any" and d.get("gender") != search_gender:
            continue
        # Фильтр по интересам
        p_interests = set((d.get("interests") or "").split(","))
        if not (set(interests) & p_interests):
            continue
        # Фильтр медиа (только для премиума)
        if media_only and viewer_is_premium:
            if not profile_has_media(d["id"]):
                continue
        seen.add(d["user_id"])
        results.append(d)
        if len(results) >= limit:
            break
    return results

def get_active_profiles_admin() -> List[Dict]:
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT p.*, u.name, u.age, u.gender, u.username, u.premium
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
        "INSERT INTO chats (profile_id, sender_id, target_id, created_at, closed) VALUES (%s,%s,%s,%s,0) RETURNING id",
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

def close_chat(chat_id: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE chats SET closed=1 WHERE id=%s", (chat_id,))
    conn.commit()
    conn.close()

def get_user_chats(user_id: int) -> List[Dict]:
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT c.*,
               (SELECT COUNT(*) FROM messages m
                WHERE m.chat_id=c.id AND m.sender_id != %s AND m.read=0) as unread
        FROM chats c
        WHERE (c.sender_id=%s OR c.target_id=%s)
          AND c.closed=0
        ORDER BY c.id DESC
    """, (user_id, user_id, user_id))
    result = _row(c, one=False)
    conn.close()
    return result

def add_message(chat_id: int, sender_id: int, content: str,
                msg_type: str = "text", file_id: str = None) -> int:
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO messages (chat_id, sender_id, content, msg_type, file_id, created_at, read) VALUES (%s,%s,%s,%s,%s,%s,0) RETURNING id",
        (chat_id, sender_id, content, msg_type, file_id, int(time.time()))
    )
    mid = c.fetchone()[0]
    conn.commit()
    conn.close()
    return mid

def mark_messages_read(chat_id: int, reader_id: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "UPDATE messages SET read=1 WHERE chat_id=%s AND sender_id != %s AND read=0",
        (chat_id, reader_id)
    )
    conn.commit()
    conn.close()

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

# ── КМН (Игры) ────────────────────────────────────────────────────────────────

def create_rps_game(chat_id: int, initiator_id: int, opponent_id: int,
                    initiator_stake_type: str, initiator_stake_fid: str,
                    wins_to: int = 3) -> int:
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS rps_games (
            id                   SERIAL PRIMARY KEY,
            chat_id              INTEGER,
            initiator_id         BIGINT,
            opponent_id          BIGINT,
            initiator_stake_type TEXT,
            initiator_stake_fid  TEXT,
            opponent_stake_type  TEXT,
            opponent_stake_fid   TEXT,
            wins_to              INTEGER DEFAULT 3,
            initiator_wins       INTEGER DEFAULT 0,
            opponent_wins        INTEGER DEFAULT 0,
            status               TEXT DEFAULT 'waiting_stake',
            initiator_move       TEXT,
            opponent_move        TEXT,
            created_at           BIGINT
        )
    """)
    c.execute("""
        INSERT INTO rps_games
            (chat_id, initiator_id, opponent_id,
             initiator_stake_type, initiator_stake_fid,
             wins_to, status, created_at)
        VALUES (%s,%s,%s,%s,%s,%s,'waiting_stake',%s)
        RETURNING id
    """, (chat_id, initiator_id, opponent_id,
          initiator_stake_type, initiator_stake_fid,
          wins_to, int(time.time())))
    gid = c.fetchone()[0]
    conn.commit()
    conn.close()
    return gid

def get_rps_game(game_id: int) -> Optional[Dict]:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM rps_games WHERE id=%s", (game_id,))
    result = _row(c)
    conn.close()
    return result

def get_active_rps_by_chat(chat_id: int) -> Optional[Dict]:
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT * FROM rps_games
        WHERE chat_id=%s AND status NOT IN ('finished','cancelled')
        ORDER BY id DESC LIMIT 1
    """, (chat_id,))
    result = _row(c)
    conn.close()
    return result

def update_rps_game(game_id: int, **kwargs):
    allowed = {
        'opponent_stake_type','opponent_stake_fid','status',
        'initiator_move','opponent_move',
        'initiator_wins','opponent_wins'
    }
    bad = set(kwargs) - allowed
    if bad:
        raise ValueError(f"Недопустимые поля: {bad}")
    conn = get_conn()
    c = conn.cursor()
    sets = ", ".join(f"{k}=%s" for k in kwargs)
    c.execute(f"UPDATE rps_games SET {sets} WHERE id=%s",
              list(kwargs.values()) + [game_id])
    conn.commit()
    conn.close()

def init_rps_table():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS rps_games (
            id                   SERIAL PRIMARY KEY,
            chat_id              INTEGER,
            initiator_id         BIGINT,
            opponent_id          BIGINT,
            initiator_stake_type TEXT,
            initiator_stake_fid  TEXT,
            opponent_stake_type  TEXT,
            opponent_stake_fid   TEXT,
            wins_to              INTEGER DEFAULT 3,
            initiator_wins       INTEGER DEFAULT 0,
            opponent_wins        INTEGER DEFAULT 0,
            status               TEXT DEFAULT 'waiting_stake',
            initiator_move       TEXT,
            opponent_move        TEXT,
            created_at           BIGINT
        )
    """)
    conn.commit()
    conn.close()

# ── КМН (Камень-Ножницы-Бумага) ───────────────────────────────────────────────

def create_kmn_game(chat_id: int, initiator_id: int, opponent_id: int,
                    wins_needed: int = 3) -> int:
    conn = get_conn()
    c = conn.cursor()
    # Создаём таблицу если нет
    c.execute("""CREATE TABLE IF NOT EXISTS kmn_games (
        id              SERIAL PRIMARY KEY,
        chat_id         INTEGER NOT NULL,
        initiator_id    BIGINT NOT NULL,
        opponent_id     BIGINT NOT NULL,
        wins_needed     INTEGER DEFAULT 3,
        initiator_wins  INTEGER DEFAULT 0,
        opponent_wins   INTEGER DEFAULT 0,
        status          TEXT DEFAULT 'waiting_stake_initiator',
        initiator_stake_file_id   TEXT,
        initiator_stake_type      TEXT,
        opponent_stake_file_id    TEXT,
        opponent_stake_type       TEXT,
        current_round   INTEGER DEFAULT 1,
        initiator_move  TEXT,
        opponent_move   TEXT,
        created_at      BIGINT,
        updated_at      BIGINT
    )""")
    c.execute("""
        INSERT INTO kmn_games
            (chat_id, initiator_id, opponent_id, wins_needed, created_at, updated_at)
        VALUES (%s,%s,%s,%s,%s,%s) RETURNING id
    """, (chat_id, initiator_id, opponent_id, wins_needed,
          int(time.time()), int(time.time())))
    gid = c.fetchone()[0]
    conn.commit()
    conn.close()
    return gid

def get_kmn_game(game_id: int) -> Optional[Dict]:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM kmn_games WHERE id=%s", (game_id,))
    result = _row(c)
    conn.close()
    return result

def get_active_kmn_by_chat(chat_id: int) -> Optional[Dict]:
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT * FROM kmn_games
        WHERE chat_id=%s AND status NOT IN ('finished','cancelled')
        ORDER BY id DESC LIMIT 1
    """, (chat_id,))
    result = _row(c)
    conn.close()
    return result

def update_kmn_game(game_id: int, **kwargs):
    allowed = {
        'status', 'initiator_wins', 'opponent_wins',
        'initiator_stake_file_id', 'initiator_stake_type',
        'opponent_stake_file_id', 'opponent_stake_type',
        'current_round', 'initiator_move', 'opponent_move', 'updated_at'
    }
    bad = set(kwargs) - allowed
    if bad:
        raise ValueError(f"Недопустимые колонки kmn: {bad}")
    kwargs['updated_at'] = int(time.time())
    conn = get_conn()
    c = conn.cursor()
    sets = ", ".join(f"{k}=%s" for k in kwargs)
    c.execute(f"UPDATE kmn_games SET {sets} WHERE id=%s",
              list(kwargs.values()) + [game_id])
    conn.commit()
    conn.close()

def init_kmn_table():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS kmn_games (
        id              SERIAL PRIMARY KEY,
        chat_id         INTEGER NOT NULL,
        initiator_id    BIGINT NOT NULL,
        opponent_id     BIGINT NOT NULL,
        wins_needed     INTEGER DEFAULT 3,
        initiator_wins  INTEGER DEFAULT 0,
        opponent_wins   INTEGER DEFAULT 0,
        status          TEXT DEFAULT 'waiting_stake_initiator',
        initiator_stake_file_id   TEXT,
        initiator_stake_type      TEXT,
        opponent_stake_file_id    TEXT,
        opponent_stake_type       TEXT,
        current_round   INTEGER DEFAULT 1,
        initiator_move  TEXT,
        opponent_move   TEXT,
        created_at      BIGINT,
        updated_at      BIGINT
    )""")
    conn.commit()
    conn.close()
