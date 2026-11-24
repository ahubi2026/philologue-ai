"""db.py — 필로로그 데이터베이스 관리 (로컬 SQLite + 클라우드 Supabase PostgreSQL 듀얼 지원)

- config.DATABASE_URL이 설정되어 있으면 클라우드 PostgreSQL(Supabase)에 연결하고,
  비어 있으면 로컬 SQLite(data/philologue.db)에 연결한다.
- 비밀번호는 원문을 저장하지 않고, 솔트(salt)를 더한 PBKDF2-SHA256 해시로만 저장한다.
"""
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta

import config

DB_PATH = config.DB_PATH
_INITIALIZED_TARGETS: set[tuple[str, str]] = set()
_INIT_LOCK = threading.Lock()


def _normalized_pg_url() -> str:
    url = (config.DATABASE_URL or "").strip()
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    return url


def is_postgres() -> bool:
    url = _normalized_pg_url()
    return url.startswith("postgresql://")


def get_db_backend() -> str:
    """현재 활성화된 DB 백엔드 이름('postgresql' 또는 'sqlite')을 반환한다."""
    return "postgresql" if is_postgres() else "sqlite"


def get_db_status_label() -> str:
    if is_postgres():
        return "☁️ 클라우드 DB (PostgreSQL / Supabase)"
    return "💾 로컬 DB (SQLite)"


def _adapt_sql(sql: str) -> str:
    """SQLite용 '?' 플레이스홀더를 PostgreSQL용 '%s'로 변환한다."""
    if is_postgres():
        return sql.replace("?", "%s")
    return sql


def _exec(conn, sql: str, params=()):
    return conn.execute(_adapt_sql(sql), params)


def _insert_returning_id(conn, sql: str, params=()) -> int:
    if is_postgres():
        cur = conn.execute(_adapt_sql(sql.rstrip().rstrip(";") + " RETURNING id"), params)
        row = cur.fetchone()
        return int(row["id"])
    cur = conn.execute(sql, params)
    return int(cur.lastrowid)


def _is_integrity_error(exc: Exception) -> bool:
    if isinstance(exc, sqlite3.IntegrityError):
        return True
    cls_name = type(exc).__name__
    return cls_name in ("IntegrityError", "UniqueViolation")


@contextmanager
def get_conn():
    """트랜잭션 처리와 연결 종료(close)를 보장하는 DB 컨텍스트 매니저."""
    if is_postgres():
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError(
                "PostgreSQL 연결을 위해 'psycopg[binary]' 패키지가 필요합니다. "
                "`pip install -r requirements.txt`를 실행해 주세요."
            ) from exc

        url = _normalized_pg_url()
        connect_kwargs = {
            "row_factory": dict_row,
            # Supabase PgBouncer Transaction Pooler(6543) 호환을 위해 prepared statement 비활성화
            "prepare_threshold": None,
            "connect_timeout": 10,
        }
        if "sslmode=" not in url and "localhost" not in url and "127.0.0.1" not in url:
            connect_kwargs["sslmode"] = "require"

        conn = psycopg.connect(url, **connect_kwargs)
        try:
            with conn:
                yield conn
        finally:
            conn.close()
    else:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()


def _ensure_column_sqlite(conn: sqlite3.Connection, table: str, column: str, col_def: str) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")


def init_db(force: bool = False) -> None:
    """앱 최초 실행 시 테이블을 생성하고 스키마 마이그레이션을 수행한다."""
    target_key = (get_db_backend(), _normalized_pg_url() if is_postgres() else str(DB_PATH))
    if not force and target_key in _INITIALIZED_TARGETS:
        return

    with _INIT_LOCK:
        if not force and target_key in _INITIALIZED_TARGETS:
            return
        _run_init_ddl()
        _INITIALIZED_TARGETS.add(target_key)


def _run_init_ddl() -> None:
    if is_postgres():
        pg_ddl = [
            "SELECT pg_advisory_xact_lock(73910421)",
            """
            CREATE TABLE IF NOT EXISTS users (
                id            SERIAL PRIMARY KEY,
                username      TEXT UNIQUE NOT NULL,
                nickname      TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                salt          TEXT NOT NULL,
                role          TEXT NOT NULL DEFAULT 'student',
                reading_level TEXT NOT NULL DEFAULT 'standard',
                pledge_agreed INTEGER NOT NULL DEFAULT 0,
                created_at    TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS answers (
                id          SERIAL PRIMARY KEY,
                user_id     INTEGER NOT NULL REFERENCES users(id),
                book_id     TEXT NOT NULL,
                question_id TEXT NOT NULL,
                answer      TEXT NOT NULL,
                created_at  TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS chat_logs (
                id            SERIAL PRIMARY KEY,
                user_id       INTEGER NOT NULL REFERENCES users(id),
                book_id       TEXT NOT NULL,
                question_id   TEXT NOT NULL,
                role          TEXT NOT NULL,
                content       TEXT NOT NULL,
                turn_no       INTEGER NOT NULL DEFAULT 0,
                reading_level TEXT NOT NULL DEFAULT 'standard',
                model_name    TEXT NOT NULL DEFAULT '',
                flagged_error INTEGER NOT NULL DEFAULT 0,
                created_at    TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS reflections (
                id                  SERIAL PRIMARY KEY,
                user_id             INTEGER NOT NULL REFERENCES users(id),
                book_id             TEXT NOT NULL,
                question_id         TEXT NOT NULL DEFAULT '',
                content             TEXT NOT NULL,
                changed_mind        TEXT NOT NULL DEFAULT '',
                discussion_question TEXT NOT NULL DEFAULT '',
                created_at          TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS sessions (
                token      TEXT PRIMARY KEY,
                user_id    INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )
            """,
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'student'",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS reading_level TEXT NOT NULL DEFAULT 'standard'",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS pledge_agreed INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE chat_logs ADD COLUMN IF NOT EXISTS turn_no INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE chat_logs ADD COLUMN IF NOT EXISTS reading_level TEXT NOT NULL DEFAULT 'standard'",
            "ALTER TABLE chat_logs ADD COLUMN IF NOT EXISTS model_name TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE chat_logs ADD COLUMN IF NOT EXISTS flagged_error INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE reflections ADD COLUMN IF NOT EXISTS question_id TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE reflections ADD COLUMN IF NOT EXISTS changed_mind TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE reflections ADD COLUMN IF NOT EXISTS discussion_question TEXT NOT NULL DEFAULT ''",
        ]
        with get_conn() as conn:
            for stmt in pg_ddl:
                conn.execute(stmt)
    else:
        with get_conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    username      TEXT UNIQUE NOT NULL,
                    nickname      TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    salt          TEXT NOT NULL,
                    role          TEXT NOT NULL DEFAULT 'student',
                    reading_level TEXT NOT NULL DEFAULT 'standard',
                    pledge_agreed INTEGER NOT NULL DEFAULT 0,
                    created_at    TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS answers (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id     INTEGER NOT NULL,
                    book_id     TEXT NOT NULL,
                    question_id TEXT NOT NULL,
                    answer      TEXT NOT NULL,
                    created_at  TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                );

                CREATE TABLE IF NOT EXISTS chat_logs (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id       INTEGER NOT NULL,
                    book_id       TEXT NOT NULL,
                    question_id   TEXT NOT NULL,
                    role          TEXT NOT NULL,
                    content       TEXT NOT NULL,
                    turn_no       INTEGER NOT NULL DEFAULT 0,
                    reading_level TEXT NOT NULL DEFAULT 'standard',
                    model_name    TEXT NOT NULL DEFAULT '',
                    flagged_error INTEGER NOT NULL DEFAULT 0,
                    created_at    TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                );

                CREATE TABLE IF NOT EXISTS reflections (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id             INTEGER NOT NULL,
                    book_id             TEXT NOT NULL,
                    question_id         TEXT NOT NULL DEFAULT '',
                    content             TEXT NOT NULL,
                    changed_mind        TEXT NOT NULL DEFAULT '',
                    discussion_question TEXT NOT NULL DEFAULT '',
                    created_at          TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    token      TEXT PRIMARY KEY,
                    user_id    INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                );
                """
            )
            _ensure_column_sqlite(conn, "users", "role", "TEXT NOT NULL DEFAULT 'student'")
            _ensure_column_sqlite(conn, "users", "reading_level", "TEXT NOT NULL DEFAULT 'standard'")
            _ensure_column_sqlite(conn, "users", "pledge_agreed", "INTEGER NOT NULL DEFAULT 0")
            _ensure_column_sqlite(conn, "chat_logs", "turn_no", "INTEGER NOT NULL DEFAULT 0")
            _ensure_column_sqlite(conn, "chat_logs", "reading_level", "TEXT NOT NULL DEFAULT 'standard'")
            _ensure_column_sqlite(conn, "chat_logs", "model_name", "TEXT NOT NULL DEFAULT ''")
            _ensure_column_sqlite(conn, "chat_logs", "flagged_error", "INTEGER NOT NULL DEFAULT 0")
            _ensure_column_sqlite(conn, "reflections", "question_id", "TEXT NOT NULL DEFAULT ''")
            _ensure_column_sqlite(conn, "reflections", "changed_mind", "TEXT NOT NULL DEFAULT ''")
            _ensure_column_sqlite(conn, "reflections", "discussion_question", "TEXT NOT NULL DEFAULT ''")


# ---------- 비밀번호 처리 ----------
def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000).hex()


# ---------- 회원가입 / 로그인 ----------
USERNAME_RULE = re.compile(r"^[A-Za-z0-9_]{4,20}$")


def create_user(username: str, nickname: str, password: str, role: str = "student"):
    """회원가입. 성공하면 (True, 안내문), 실패하면 (False, 오류문)을 돌려준다."""
    username, nickname = username.strip(), nickname.strip()
    if not USERNAME_RULE.match(username):
        return False, "아이디는 영문·숫자·밑줄(_)로 4~20자여야 합니다."
    if not (1 <= len(nickname) <= 10):
        return False, "별명은 1~10자로 입력해 주세요."
    if len(password) < 6:
        return False, "비밀번호는 6자 이상이어야 합니다."

    salt = os.urandom(16)
    try:
        with get_conn() as conn:
            _exec(
                conn,
                """
                INSERT INTO users (username, nickname, password_hash, salt, role, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    username,
                    nickname,
                    _hash_password(password, salt),
                    salt.hex(),
                    role,
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
    except Exception as exc:
        if _is_integrity_error(exc):
            return False, "이미 사용 중인 아이디입니다."
        raise
    return True, "회원가입이 완료되었습니다. 로그인해 주세요."


def verify_user(username: str, password: str) -> dict | None:
    """로그인. 맞으면 사용자 정보(dict), 틀리면 None을 돌려준다."""
    with get_conn() as conn:
        row = _exec(conn, "SELECT * FROM users WHERE username = ?", (username.strip(),)).fetchone()
    if row is None:
        return None
    expected = _hash_password(password, bytes.fromhex(row["salt"]))
    if not hmac.compare_digest(expected, row["password_hash"]):
        return None
    return {
        "id": row["id"],
        "username": row["username"],
        "nickname": row["nickname"],
        "role": row["role"],
        "reading_level": row["reading_level"],
        "pledge_agreed": bool(row["pledge_agreed"]),
    }


def set_pledge_agreed(user_id: int) -> None:
    """0단계 AI 사용 약속 동의를 저장한다."""
    with get_conn() as conn:
        _exec(conn, "UPDATE users SET pledge_agreed = 1 WHERE id = ?", (user_id,))


# ---------- 로그인 세션 토큰 (F5 새로고침 유지) ----------
def create_session(user_id: int, ttl_hours: int = 24) -> str:
    """암호학적 랜덤 세션 토큰을 생성해 DB에 저장한다."""
    now = datetime.now()
    expires = now + timedelta(hours=ttl_hours)
    token = secrets.token_urlsafe(24)
    with get_conn() as conn:
        _exec(conn, "DELETE FROM sessions WHERE expires_at < ?", (now.isoformat(timespec="seconds"),))
        _exec(
            conn,
            "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token, user_id, now.isoformat(timespec="seconds"), expires.isoformat(timespec="seconds")),
        )
    return token


def get_user_by_session(token: str) -> dict | None:
    """유효한 세션 토큰이면 최신 사용자 정보(dict), 만료/무효이면 None을 반환한다."""
    if not token:
        return None
    now_iso = datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        row = _exec(
            conn,
            """
            SELECT u.id, u.username, u.nickname, u.role, u.reading_level, u.pledge_agreed, s.expires_at
            FROM sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token = ?
            """,
            (token,),
        ).fetchone()
        if row is None:
            return None
        if row["expires_at"] < now_iso:
            _exec(conn, "DELETE FROM sessions WHERE token = ?", (token,))
            return None
    return {
        "id": row["id"],
        "username": row["username"],
        "nickname": row["nickname"],
        "role": row["role"],
        "reading_level": row["reading_level"],
        "pledge_agreed": bool(row["pledge_agreed"]),
    }


def delete_session(token: str) -> None:
    """로그아웃 시 DB에서 세션 토큰을 즉시 삭제한다."""
    if not token:
        return
    with get_conn() as conn:
        _exec(conn, "DELETE FROM sessions WHERE token = ?", (token,))


def update_reading_level(user_id: int, reading_level: str) -> None:
    """학습자의 독해 수준('basic' | 'standard' | 'advanced')을 갱신한다."""
    if reading_level not in config.READING_LEVELS:
        raise ValueError(f"Unsupported reading_level: {reading_level}")
    with get_conn() as conn:
        _exec(conn, "UPDATE users SET reading_level = ? WHERE id = ?", (reading_level, user_id))


# ---------- 4단계: 문항별 답변 ----------
def save_answer(user_id: int, book_id: str, question_id: str, answer: str) -> None:
    """답변을 저장한다. 고칠 때마다 새 행으로 쌓아 수정 이력을 연구 자료로 남긴다."""
    with get_conn() as conn:
        _exec(
            conn,
            "INSERT INTO answers (user_id, book_id, question_id, answer, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, book_id, question_id, answer.strip(), datetime.now().isoformat(timespec="seconds")),
        )


def get_latest_answer(user_id: int, question_id: str) -> dict | None:
    """가장 최근에 저장한 답변(dict) 또는 None."""
    with get_conn() as conn:
        row = _exec(
            conn,
            "SELECT answer, created_at FROM answers WHERE user_id = ? AND question_id = ? ORDER BY id DESC LIMIT 1",
            (user_id, question_id),
        ).fetchone()
    return dict(row) if row else None


def get_answered_question_ids(user_id: int, book_id: str) -> set[str]:
    """이 책에서 답변을 저장한 문항 id 모음(도서 상세 화면의 ✅ 표시용)."""
    with get_conn() as conn:
        rows = _exec(
            conn,
            "SELECT DISTINCT question_id FROM answers WHERE user_id = ? AND book_id = ?",
            (user_id, book_id),
        ).fetchall()
    return {r["question_id"] for r in rows}


# ---------- 5단계: 소크라테스 AI 대화 로그 ----------
def save_chat_message(
    user_id: int,
    book_id: str,
    question_id: str,
    role: str,
    content: str,
    turn_no: int = 0,
    reading_level: str = "standard",
    model_name: str = "",
) -> int:
    """대화 메시지 1건을 연구용 로그로 저장하고 생성된 행 id를 돌려준다."""
    with get_conn() as conn:
        return _insert_returning_id(
            conn,
            """
            INSERT INTO chat_logs
                (user_id, book_id, question_id, role, content, turn_no, reading_level, model_name, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                book_id,
                question_id,
                role,
                content.strip(),
                turn_no,
                reading_level,
                model_name,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )


def get_chat_logs(user_id: int, question_id: str) -> list[dict]:
    """특정 문항의 대화 로그를 시간순으로 돌려준다."""
    with get_conn() as conn:
        rows = _exec(
            conn,
            """
            SELECT id, role, content, turn_no, reading_level, model_name, flagged_error, created_at
            FROM chat_logs
            WHERE user_id = ? AND question_id = ?
            ORDER BY id ASC
            """,
            (user_id, question_id),
        ).fetchall()
    return [dict(r) for r in rows]


def count_user_turns(user_id: int, question_id: str) -> int:
    """특정 문항에서 학생('user')이 답한 턴 수를 반환한다."""
    with get_conn() as conn:
        row = _exec(
            conn,
            "SELECT COUNT(*) AS cnt FROM chat_logs WHERE user_id = ? AND question_id = ? AND role = 'user'",
            (user_id, question_id),
        ).fetchone()
    return int(row["cnt"]) if row else 0


def toggle_flag_error(log_id: int, user_id: int) -> bool:
    """학생이 AI 응답의 본문 오류/환각 의심 표시를 토글한다. 변경 후 상태를 반환한다."""
    with get_conn() as conn:
        row = _exec(
            conn,
            "SELECT flagged_error FROM chat_logs WHERE id = ? AND user_id = ? AND role = 'assistant'",
            (log_id, user_id),
        ).fetchone()
        if row is None:
            return False
        new_val = 0 if row["flagged_error"] else 1
        _exec(
            conn,
            "UPDATE chat_logs SET flagged_error = ? WHERE id = ? AND user_id = ?",
            (new_val, log_id, user_id),
        )
        return bool(new_val)


def get_chatted_question_ids(user_id: int, book_id: str) -> set[str]:
    """이 책에서 학생이 1턴 이상 AI와 대화한 문항 id 모음."""
    with get_conn() as conn:
        rows = _exec(
            conn,
            "SELECT DISTINCT question_id FROM chat_logs WHERE user_id = ? AND book_id = ? AND role = 'user'",
            (user_id, book_id),
        ).fetchall()
    return {r["question_id"] for r in rows}


# ---------- 6단계: 성찰일지 및 최종 판단 ----------
def save_reflection(
    user_id: int,
    book_id: str,
    question_id: str,
    content: str,
    changed_mind: str,
    discussion_question: str,
) -> int:
    """성찰일지와 최종 판단을 저장한다. 수정 이력을 남기기 위해 새 행으로 누적한다."""
    with get_conn() as conn:
        return _insert_returning_id(
            conn,
            """
            INSERT INTO reflections
                (user_id, book_id, question_id, content, changed_mind, discussion_question, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                book_id,
                question_id,
                content.strip(),
                changed_mind.strip(),
                discussion_question.strip(),
                datetime.now().isoformat(timespec="seconds"),
            ),
        )


def get_latest_reflection(user_id: int, question_id: str) -> dict | None:
    """특정 문항의 가장 최근 성찰일지(dict) 또는 None."""
    with get_conn() as conn:
        row = _exec(
            conn,
            """
            SELECT id, content, changed_mind, discussion_question, created_at
            FROM reflections
            WHERE user_id = ? AND question_id = ?
            ORDER BY id DESC LIMIT 1
            """,
            (user_id, question_id),
        ).fetchone()
    return dict(row) if row else None


def get_reflected_question_ids(user_id: int, book_id: str) -> set[str]:
    """이 책에서 성찰일지를 저장한 문항 id 모음."""
    with get_conn() as conn:
        rows = _exec(
            conn,
            "SELECT DISTINCT question_id FROM reflections WHERE user_id = ? AND book_id = ? AND question_id != ''",
            (user_id, book_id),
        ).fetchall()
    return {r["question_id"] for r in rows}


# ---------- 7단계: 교사·연구자 대시보드 및 익명 데이터 추출 ----------
def get_anon_code_map() -> dict[int, str]:
    """모든 학생 계정(role='student')을 가입순 익명 참여번호(S001, S002...)로 매핑한다."""
    with get_conn() as conn:
        rows = _exec(
            conn,
            "SELECT id FROM users WHERE role = 'student' ORDER BY id ASC",
        ).fetchall()
    return {row["id"]: f"S{idx:03d}" for idx, row in enumerate(rows, start=1)}


def list_students_with_stats() -> list[dict]:
    """학생 목록과 각 학생의 4·5·6단계 활동 요약 통계를 반환한다."""
    anon_map = get_anon_code_map()
    with get_conn() as conn:
        rows = _exec(
            conn,
            """
            SELECT
                u.id,
                u.username,
                u.nickname,
                u.reading_level,
                u.pledge_agreed,
                u.created_at,
                (SELECT COUNT(DISTINCT question_id) FROM answers a WHERE a.user_id = u.id) AS answered_q,
                (SELECT COUNT(DISTINCT question_id) FROM chat_logs c WHERE c.user_id = u.id AND c.role = 'user') AS chatted_q,
                (SELECT COUNT(*) FROM chat_logs c WHERE c.user_id = u.id AND c.role = 'user') AS user_turns,
                (SELECT COUNT(DISTINCT question_id) FROM reflections r WHERE r.user_id = u.id AND r.question_id != '') AS reflected_q,
                (SELECT COUNT(*) FROM chat_logs c WHERE c.user_id = u.id AND c.flagged_error = 1) AS flagged_cnt
            FROM users u
            WHERE u.role = 'student'
            ORDER BY u.id ASC
            """,
        ).fetchall()
    result = []
    for r in rows:
        item = dict(r)
        item["anon_id"] = anon_map.get(r["id"], f"S{r['id']:03d}")
        result.append(item)
    return result


def get_student_questions_summary(user_id: int) -> list[dict]:
    """특정 학생이 1차 해석·대화·성찰을 남긴 문항 목록과 요약을 반환한다."""
    with get_conn() as conn:
        rows = _exec(
            conn,
            """
            SELECT
                q.book_id,
                q.question_id,
                (SELECT COUNT(*) FROM answers a WHERE a.user_id = ? AND a.question_id = q.question_id) AS answer_revs,
                (SELECT COUNT(*) FROM chat_logs c WHERE c.user_id = ? AND c.question_id = q.question_id AND c.role = 'user') AS user_turns,
                (SELECT COUNT(*) FROM reflections r WHERE r.user_id = ? AND r.question_id = q.question_id) AS reflection_revs,
                (SELECT COUNT(*) FROM chat_logs c WHERE c.user_id = ? AND c.question_id = q.question_id AND c.flagged_error = 1) AS flagged_cnt
            FROM (
                SELECT book_id, question_id FROM answers WHERE user_id = ?
                UNION
                SELECT book_id, question_id FROM chat_logs WHERE user_id = ?
                UNION
                SELECT book_id, question_id FROM reflections WHERE user_id = ? AND question_id != ''
            ) AS q
            ORDER BY q.book_id ASC, q.question_id ASC
            """,
            (user_id, user_id, user_id, user_id, user_id, user_id, user_id),
        ).fetchall()
    return [dict(r) for r in rows]


def get_answer_history(user_id: int, question_id: str) -> list[dict]:
    """특정 문항의 1차 해석 수정 이력 전체를 시간순으로 반환한다."""
    with get_conn() as conn:
        rows = _exec(
            conn,
            "SELECT id, answer, created_at FROM answers WHERE user_id = ? AND question_id = ? ORDER BY id ASC",
            (user_id, question_id),
        ).fetchall()
    return [dict(r) for r in rows]


def get_reflection_history(user_id: int, question_id: str) -> list[dict]:
    """특정 문항의 성찰일지 수정 이력 전체를 시간순으로 반환한다."""
    with get_conn() as conn:
        rows = _exec(
            conn,
            """
            SELECT id, content, changed_mind, discussion_question, created_at
            FROM reflections
            WHERE user_id = ? AND question_id = ?
            ORDER BY id ASC
            """,
            (user_id, question_id),
        ).fetchall()
    return [dict(r) for r in rows]


def get_flagged_chat_logs() -> list[dict]:
    """학생들이 '책과 다른 내용'으로 표시한 AI 응답 로그 전체를 반환한다."""
    anon_map = get_anon_code_map()
    with get_conn() as conn:
        rows = _exec(
            conn,
            """
            SELECT c.id, c.user_id, u.nickname, c.book_id, c.question_id, c.turn_no,
                   c.reading_level, c.model_name, c.content, c.created_at
            FROM chat_logs c
            JOIN users u ON u.id = c.user_id
            WHERE c.flagged_error = 1
            ORDER BY c.id DESC
            """,
        ).fetchall()
    out = []
    for r in rows:
        item = dict(r)
        item["anon_id"] = anon_map.get(r["user_id"], f"U{r['user_id']:03d}")
        out.append(item)
    return out


def get_latest_discussion_questions(book_id: str | None = None) -> list[dict]:
    """공동체 토론 수업을 위해 학생별·문항별 최신 토론 질문을 모아 반환한다."""
    anon_map = get_anon_code_map()
    sql = """
        SELECT r.user_id, u.nickname, r.book_id, r.question_id, r.changed_mind, r.discussion_question, r.created_at
        FROM reflections r
        JOIN users u ON u.id = r.user_id
        WHERE r.id IN (
            SELECT MAX(id) FROM reflections WHERE discussion_question != '' GROUP BY user_id, question_id
        )
    """
    params: list = []
    if book_id:
        sql += " AND r.book_id = ?"
        params.append(book_id)
    sql += " ORDER BY r.book_id ASC, r.question_id ASC, r.created_at DESC"
    with get_conn() as conn:
        rows = _exec(conn, sql, tuple(params)).fetchall()
    out = []
    for r in rows:
        item = dict(r)
        item["anon_id"] = anon_map.get(r["user_id"], f"U{r['user_id']:03d}")
        out.append(item)
    return out


def export_anonymized_datasets() -> dict[str, list[dict]]:
    """연구 분석용 익명 데이터셋(학생 role='student' 대상, 실명·아이디·별명 완전 제거)을 반환한다."""
    anon_map = get_anon_code_map()
    with get_conn() as conn:
        answers_rows = _exec(
            conn,
            """
            SELECT a.id, a.user_id, u.reading_level, a.book_id, a.question_id, a.answer, a.created_at
            FROM answers a
            JOIN users u ON u.id = a.user_id
            WHERE u.role = 'student'
            ORDER BY a.user_id ASC, a.id ASC
            """,
        ).fetchall()

        chat_rows = _exec(
            conn,
            """
            SELECT c.id, c.user_id, c.book_id, c.question_id, c.turn_no, c.role,
                   c.reading_level, c.model_name, c.flagged_error, c.content, c.created_at
            FROM chat_logs c
            JOIN users u ON u.id = c.user_id
            WHERE u.role = 'student'
            ORDER BY c.user_id ASC, c.book_id ASC, c.question_id ASC, c.id ASC
            """,
        ).fetchall()

        ref_rows = _exec(
            conn,
            """
            SELECT r.id, r.user_id, u.reading_level, r.book_id, r.question_id,
                   r.changed_mind, r.content, r.discussion_question, r.created_at
            FROM reflections r
            JOIN users u ON u.id = r.user_id
            WHERE u.role = 'student'
            ORDER BY r.user_id ASC, r.id ASC
            """,
        ).fetchall()

    answers = [
        {
            "record_id": r["id"],
            "anon_id": anon_map[r["user_id"]],
            "reading_level": r["reading_level"],
            "book_id": r["book_id"],
            "question_id": r["question_id"],
            "char_len": len(r["answer"]),
            "answer": r["answer"],
            "created_at": r["created_at"],
        }
        for r in answers_rows
    ]

    chat_logs = [
        {
            "log_id": r["id"],
            "anon_id": anon_map[r["user_id"]],
            "book_id": r["book_id"],
            "question_id": r["question_id"],
            "turn_no": r["turn_no"],
            "role": r["role"],
            "reading_level": r["reading_level"],
            "model_name": r["model_name"],
            "flagged_error": r["flagged_error"],
            "content": r["content"],
            "created_at": r["created_at"],
        }
        for r in chat_rows
    ]

    reflections = [
        {
            "record_id": r["id"],
            "anon_id": anon_map[r["user_id"]],
            "reading_level": r["reading_level"],
            "book_id": r["book_id"],
            "question_id": r["question_id"],
            "changed_mind": r["changed_mind"],
            "char_len": len(r["content"]),
            "final_judgment": r["content"],
            "discussion_question": r["discussion_question"],
            "created_at": r["created_at"],
        }
        for r in ref_rows
    ]

    coding_pairs: list[dict] = []
    grouped: dict[tuple[int, str], list] = {}
    for r in chat_rows:
        grouped.setdefault((r["user_id"], r["question_id"]), []).append(r)

    for (uid, qid), seq in grouped.items():
        pair_idx = 0
        i = 0
        while i < len(seq):
            cur = seq[i]
            if cur["role"] == "assistant":
                pair_idx += 1
                next_user = seq[i + 1] if (i + 1 < len(seq) and seq[i + 1]["role"] == "user") else None
                coding_pairs.append(
                    {
                        "anon_id": anon_map[uid],
                        "book_id": cur["book_id"],
                        "question_id": qid,
                        "pair_no": pair_idx,
                        "reading_level": cur["reading_level"],
                        "model_name": cur["model_name"],
                        "flagged_error": cur["flagged_error"],
                        "ai_question": cur["content"],
                        "student_response": next_user["content"] if next_user else "",
                        "ai_code_Q1_Q5_QX_QR": "",
                        "student_code_E0_E3": "",
                        "coder_memo": "",
                    }
                )
                i += 2 if next_user else 1
            else:
                i += 1

    return {
        "answers": answers,
        "chat_logs": chat_logs,
        "reflections": reflections,
        "coding_pairs": coding_pairs,
    }


def get_comparison_records(user_ids: list[int] | None = None) -> list[dict]:
    """학생 간 비교 분석용 문항별 통합 레코드(최신 1차 해석 + 대화 턴 + 최신 성찰)를 반환한다."""
    anon_map = get_anon_code_map()
    with get_conn() as conn:
        if user_ids:
            placeholders = ",".join("?" for _ in user_ids)
            user_rows = _exec(
                conn,
                f"SELECT id, username, nickname, reading_level FROM users WHERE id IN ({placeholders}) ORDER BY id ASC",
                tuple(user_ids),
            ).fetchall()
        else:
            user_rows = _exec(
                conn,
                "SELECT id, username, nickname, reading_level FROM users WHERE role = 'student' ORDER BY id ASC",
            ).fetchall()

        records: list[dict] = []
        for u in user_rows:
            uid = u["id"]
            q_rows = _exec(
                conn,
                """
                SELECT DISTINCT sub.book_id, sub.question_id FROM (
                    SELECT book_id, question_id FROM answers WHERE user_id = ?
                    UNION
                    SELECT book_id, question_id FROM reflections WHERE user_id = ? AND question_id != ''
                ) AS sub
                ORDER BY sub.book_id ASC, sub.question_id ASC
                """,
                (uid, uid),
            ).fetchall()

            for qr in q_rows:
                bid, qid = qr["book_id"], qr["question_id"]
                ans = _exec(
                    conn,
                    "SELECT answer, created_at FROM answers WHERE user_id = ? AND question_id = ? ORDER BY id DESC LIMIT 1",
                    (uid, qid),
                ).fetchone()
                ref = _exec(
                    conn,
                    """
                    SELECT content, changed_mind, discussion_question, created_at
                    FROM reflections WHERE user_id = ? AND question_id = ? ORDER BY id DESC LIMIT 1
                    """,
                    (uid, qid),
                ).fetchone()
                chat_stat = _exec(
                    conn,
                    """
                    SELECT
                        SUM(CASE WHEN role = 'user' THEN 1 ELSE 0 END) AS user_turns,
                        SUM(CASE WHEN flagged_error = 1 THEN 1 ELSE 0 END) AS flagged_cnt
                    FROM chat_logs WHERE user_id = ? AND question_id = ?
                    """,
                    (uid, qid),
                ).fetchone()

                ans_text = ans["answer"] if ans else ""
                ref_text = ref["content"] if ref else ""
                records.append(
                    {
                        "user_id": uid,
                        "anon_id": anon_map.get(uid, f"S{uid:03d}"),
                        "username": u["username"],
                        "nickname": u["nickname"],
                        "reading_level": u["reading_level"],
                        "book_id": bid,
                        "question_id": qid,
                        "answer": ans_text,
                        "answer_len": len(ans_text),
                        "user_turns": int(chat_stat["user_turns"] or 0) if chat_stat else 0,
                        "flagged_cnt": int(chat_stat["flagged_cnt"] or 0) if chat_stat else 0,
                        "final_judgment": ref_text,
                        "final_len": len(ref_text),
                        "changed_mind": ref["changed_mind"] if ref else "",
                        "discussion_question": ref["discussion_question"] if ref else "",
                    }
                )
    return records
