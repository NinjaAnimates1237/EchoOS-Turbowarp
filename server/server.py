import os
import re
import asyncio
import hmac
import base64
import hashlib
import secrets
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Header, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

try:
    import psycopg
except Exception:
    psycopg = None


app = FastAPI(title="Echo WebSocket Server")

ADMIN_KEY = os.getenv("ADMIN_KEY", "change-me")
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
SQLITE_PATH = os.getenv("SQLITE_PATH", "data.db")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql://" + DATABASE_URL[len("postgres://"):]

clients: set[WebSocket] = set()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def use_postgres() -> bool:
    return bool(DATABASE_URL)


def db_connect():
    if use_postgres():
        if psycopg is None:
            raise RuntimeError(
                "DATABASE_URL is set but psycopg is not installed"
            )

        return psycopg.connect(DATABASE_URL)

    conn = sqlite3.connect(
        SQLITE_PATH,
        check_same_thread=False
    )

    conn.row_factory = sqlite3.Row
    return conn


def sql(query: str) -> str:
    if use_postgres():
        return query.replace("?", "%s")

    return query


def init_db():
    with db_connect() as conn:
        cur = conn.cursor()

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS user_info (
                user_id TEXT NOT NULL,
                info_key TEXT NOT NULL,
                info_value TEXT NOT NULL,
                PRIMARY KEY (user_id, info_key)
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS server_settings (
                setting_key TEXT PRIMARY KEY,
                setting_value TEXT NOT NULL
            )
            """
        )

        cur.execute(
            sql(
                "SELECT setting_value "
                "FROM server_settings "
                "WHERE setting_key = ?"
            ),
            ("enabled",),
        )

        row = cur.fetchone()

        if row is None:
            cur.execute(
                sql(
                    "INSERT INTO server_settings"
                    "(setting_key, setting_value) "
                    "VALUES (?, ?)"
                ),
                ("enabled", "1"),
            )

        conn.commit()


@app.on_event("startup")
def startup():
    init_db()


def server_enabled():
    with db_connect() as conn:
        cur = conn.cursor()

        cur.execute(
            sql(
                "SELECT setting_value "
                "FROM server_settings "
                "WHERE setting_key = ?"
            ),
            ("enabled",),
        )

        row = cur.fetchone()

        if row is None:
            return True

        if isinstance(row, sqlite3.Row):
            value = row["setting_value"]
        else:
            value = row[0]

        return str(value) == "1"


def set_server_enabled(enabled: bool):
    value = "1" if enabled else "0"

    with db_connect() as conn:
        cur = conn.cursor()

        if use_postgres():
            cur.execute(
                """
                INSERT INTO server_settings(
                    setting_key,
                    setting_value
                )
                VALUES (%s, %s)

                ON CONFLICT (setting_key)
                DO UPDATE SET
                setting_value = EXCLUDED.setting_value
                """,
                ("enabled", value),
            )

        else:
            cur.execute(
                """
                INSERT INTO server_settings(
                    setting_key,
                    setting_value
                )
                VALUES (?, ?)

                ON CONFLICT(setting_key)
                DO UPDATE SET
                setting_value = excluded.setting_value
                """,
                ("enabled", value),
            )

        conn.commit()


def hash_password(password: str):
    salt = secrets.token_bytes(16)

    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        210_000,
    )

    return (
        "pbkdf2_sha256$210000$"
        + base64.b64encode(salt).decode()
        + "$"
        + base64.b64encode(digest).decode()
    )


def verify_password(password: str, encoded: str):
    try:
        algo, rounds, salt_b64, digest_b64 = encoded.split("$", 3)

        if algo != "pbkdf2_sha256":
            return False

        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)

        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            int(rounds),
        )

        return hmac.compare_digest(
            actual,
            expected
        )

    except Exception:
        return False


def register_user(
    username: str,
    user_id: str,
    password: str
):
    username = username.strip()
    user_id = user_id.strip()

    if not username or not user_id or not password:
        return False, "REGISTER_ERROR:missing_field"

    if (
        len(username) > 64
        or len(user_id) > 64
        or len(password) > 256
    ):
        return False, "REGISTER_ERROR:field_too_long"

    try:
        with db_connect() as conn:
            cur = conn.cursor()

            cur.execute(
                sql(
                    "INSERT INTO users("
                    "user_id, username, password_hash, created_at"
                    ") VALUES (?, ?, ?, ?)"
                ),
                (
                    user_id,
                    username,
                    hash_password(password),
                    now_iso(),
                ),
            )

            conn.commit()

        return True, "REGISTERED"

    except Exception as exc:
        text = str(exc).lower()

        if "unique" in text or "duplicate" in text:
            return False, "REGISTER_ERROR:user_exists"

        return False, "REGISTER_ERROR:database"


def login_user(username: str, password: str):
    with db_connect() as conn:
        cur = conn.cursor()

        cur.execute(
            sql(
                "SELECT user_id, password_hash "
                "FROM users "
                "WHERE username = ?"
            ),
            (username.strip(),),
        )

        row = cur.fetchone()

        if row is None:
            return False, "LOGIN_ERROR"

        user_id = row[0]
        password_hash = row[1]

        if verify_password(password, password_hash):
            return True, f"LOGIN_OK:{user_id}"

        return False, "LOGIN_ERROR"


def set_info(
    user_id: str,
    key: str,
    value: str
):
    user_id = user_id.strip()
    key = key.strip()

    if not user_id or not key:
        return "SETINFO_ERROR:missing_field"

    if key.lower() in {
        "password",
        "password_hash"
    }:
        return "SETINFO_ERROR:reserved_key"

    with db_connect() as conn:
        cur = conn.cursor()

        cur.execute(
            sql(
                "SELECT user_id "
                "FROM users "
                "WHERE user_id = ?"
            ),
            (user_id,),
        )

        if cur.fetchone() is None:
            return "SETINFO_ERROR:user_not_found"

        if use_postgres():
            cur.execute(
                """
                INSERT INTO user_info(
                    user_id,
                    info_key,
                    info_value
                )
                VALUES (%s, %s, %s)

                ON CONFLICT (
                    user_id,
                    info_key
                )

                DO UPDATE SET
                info_value = EXCLUDED.info_value
                """,
                (
                    user_id,
                    key,
                    value,
                ),
            )

        else:
            cur.execute(
                """
                INSERT INTO user_info(
                    user_id,
                    info_key,
                    info_value
                )
                VALUES (?, ?, ?)

                ON CONFLICT(
                    user_id,
                    info_key
                )

                DO UPDATE SET
                info_value = excluded.info_value
                """,
                (
                    user_id,
                    key,
                    value,
                ),
            )

        conn.commit()

    return "SETINFO_OK"


def find_user(identifier: str) -> Optional[dict]:
    identifier = identifier.strip()

    with db_connect() as conn:
        cur = conn.cursor()

        cur.execute(
            sql(
                "SELECT user_id, username, created_at "
                "FROM users "
                "WHERE user_id = ? OR username = ?"
            ),
            (
                identifier,
                identifier,
            ),
        )

        row = cur.fetchone()

        if row is None:
            return None

        user_id = row[0]
        username = row[1]
        created_at = row[2]

        cur.execute(
            sql(
                "SELECT info_key, info_value "
                "FROM user_info "
                "WHERE user_id = ? "
                "ORDER BY info_key"
            ),
            (user_id,),
        )

        extra_rows = cur.fetchall()

    info = {
        "username": username,
        "id": user_id,
        "created_at": created_at,
    }

    for extra in extra_rows:
        info[str(extra[0])] = str(extra[1])

    return info


async def send_user_separately(
    websocket: WebSocket,
    identifier: str
):
    user = find_user(identifier)

    if not user:
        await websocket.send_text(
            "USER_NOT_FOUND"
        )
        return

    # Start
    await websocket.send_text(
        "BEGIN_USER"
    )

    await asyncio.sleep(0.08)

    # EACH ITEM IS SENT AS
    # A SEPARATE WEBSOCKET MESSAGE
    for key, value in user.items():

        await websocket.send_text(
            f"{key}:{value}"
        )

        await asyncio.sleep(0.08)

    # Finished
    await websocket.send_text(
        "END_USER"
    )


async def read_next(
    websocket: WebSocket
):
    try:
        return await websocket.receive_text()

    except WebSocketDisconnect:
        return None


@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket
):

    if not server_enabled():
        await websocket.close(
            code=1013,
            reason="Server is turned off"
        )
        return

    await websocket.accept()

    clients.add(websocket)

    await websocket.send_text(
        "CONNECTED"
    )

    try:

        while True:

            message = (
                await websocket.receive_text()
            ).strip()

            command = message.lower()

            # ------------------------
            # PING
            # ------------------------

            if command == "ping":

                await websocket.send_text(
                    "pong"
                )

            # ------------------------
            # REGISTER COMMAND
            # ------------------------

            elif command == "register":

                await websocket.send_text(
                    "SEND_USERNAME"
                )

                username = await read_next(
                    websocket
                )

                if username is None:
                    break

                await websocket.send_text(
                    "SEND_PASSWORD"
                )

                password = await read_next(
                    websocket
                )

                if password is None:
                    break

                await websocket.send_text(
                    "SEND_ID"
                )

                user_id = await read_next(
                    websocket
                )

                if user_id is None:
                    break

                _, reply = register_user(
                    username,
                    user_id,
                    password
                )

                await websocket.send_text(
                    reply
                )

            # ------------------------
            # LOGIN
            # ------------------------

            elif command == "login":

                await websocket.send_text(
                    "SEND_USERNAME"
                )

                username = await read_next(
                    websocket
                )

                if username is None:
                    break

                await websocket.send_text(
                    "SEND_PASSWORD"
                )

                password = await read_next(
                    websocket
                )

                if password is None:
                    break

                _, reply = login_user(
                    username,
                    password
                )

                await websocket.send_text(
                    reply
                )

            # ------------------------
            # SAVE EXTRA INFORMATION
            # ------------------------

            elif command == "setinfo":

                await websocket.send_text(
                    "SEND_ID"
                )

                user_id = await read_next(
                    websocket
                )

                if user_id is None:
                    break

                await websocket.send_text(
                    "SEND_KEY"
                )

                key = await read_next(
                    websocket
                )

                if key is None:
                    break

                await websocket.send_text(
                    "SEND_VALUE"
                )

                value = await read_next(
                    websocket
                )

                if value is None:
                    break

                result = set_info(
                    user_id,
                    key,
                    value
                )

                await websocket.send_text(
                    result
                )

            # ------------------------
            # getUserID
            # then ID separately
            # ------------------------

            elif command == "getuserid":

                await websocket.send_text(
                    "SEND_ID_OR_USERNAME"
                )

                identifier = await read_next(
                    websocket
                )

                if identifier is None:
                    break

                await send_user_separately(
                    websocket,
                    identifier
                )

            # ------------------------
            # getUserID 12345
            # ------------------------

            elif command.startswith(
                "getuserid "
            ):

                identifier = message.split(
                    " ",
                    1
                )[1]

                await send_user_separately(
                    websocket,
                    identifier
                )

            # ------------------------
            # EXACTLY YOUR SCRATCH BLOCK
            #
            # GetUserID(12345)
            # ------------------------

            elif re.fullmatch(
                r"(?i)getuserid\s*\(.*\)",
                message
            ):

                identifier = re.sub(
                    r"(?i)^getuserid\s*\(",
                    "",
                    message
                )

                identifier = re.sub(
                    r"\)\s*$",
                    "",
                    identifier
                ).strip()

                if identifier:

                    await send_user_separately(
                        websocket,
                        identifier
                    )

                else:

                    await websocket.send_text(
                        "USER_NOT_FOUND"
                    )

            # ------------------------
            # HELP
            # ------------------------

            elif command == "help":

                commands = [
                    "COMMAND:register",
                    "COMMAND:login",
                    "COMMAND:setInfo",
                    "COMMAND:getUserID",
                    "COMMAND:GetUserID(ID)",
                    "END_HELP",
                ]

                for line in commands:

                    await websocket.send_text(
                        line
                    )

            # ------------------------
            # YOUR CURRENT SCRATCH
            # REGISTRATION SYSTEM
            #
            # Your blocks send:
            #
            # username
            # password
            # ID
            #
            # WITHOUT sending "register"
            # first.
            # ------------------------

            else:

                username = message

                password = await read_next(
                    websocket
                )

                if password is None:
                    break

                user_id = await read_next(
                    websocket
                )

                if user_id is None:
                    break

                _, reply = register_user(
                    username,
                    user_id,
                    password
                )

                await websocket.send_text(
                    reply
                )

    except WebSocketDisconnect:
        pass

    finally:
        clients.discard(websocket)


# ==========================
# WEBSITE
# ==========================

@app.get("/")
def home():

    if use_postgres():
        db_name = "PostgreSQL"
    else:
        db_name = "SQLite"

    return JSONResponse(
        {
            "ok": True,
            "websocket": "/ws",
            "control": "/control",
            "enabled": server_enabled(),
            "database": db_name,
        }
    )


CONTROL_HTML = """
<!doctype html>

<html>

<head>

<meta charset="utf-8">

<meta
name="viewport"
content="width=device-width,initial-scale=1"
>

<title>
Echo WebSocket Control
</title>

<style>

body {
    font-family: system-ui, sans-serif;
    max-width: 640px;
    margin: 50px auto;
    padding: 0 20px;
    background: #111;
    color: #eee;
}

input,
button {
    font-size: 18px;
    padding: 12px;
    margin: 6px 3px;
    border-radius: 9px;
    border: 1px solid #555;
}

input {
    width: min(390px, 90%);
    background: #222;
    color: white;
}

button {
    cursor: pointer;
}

#status {
    margin-top: 18px;
    font-weight: 700;
}

</style>

</head>

<body>

<h1>
Echo WebSocket Server
</h1>

<p>
Enter your ADMIN_KEY to turn
the WebSocket server on or off.
</p>

<input
id="key"
type="password"
placeholder="ADMIN_KEY"
>

<div>

<button onclick="setState('on')">
Turn ON
</button>

<button onclick="setState('off')">
Turn OFF
</button>

<button onclick="check()">
Check Status
</button>

</div>

<div id="status"></div>

<script>

async function setState(state) {

    const key =
        document.getElementById(
            'key'
        ).value;

    const response =
        await fetch(
            '/api/' + state,
            {
                method: 'POST',

                headers: {
                    'X-Admin-Key': key
                }
            }
        );

    document.getElementById(
        'status'
    ).textContent =
        await response.text();
}


async function check() {

    const response =
        await fetch(
            '/api/status'
        );

    document.getElementById(
        'status'
    ).textContent =
        await response.text();
}

check();

</script>

</body>

</html>
"""


@app.get(
    "/control",
    response_class=HTMLResponse
)
def control():

    return CONTROL_HTML


@app.get("/api/status")
def status():

    return {
        "enabled": server_enabled(),
        "connected_clients": len(clients)
    }


def require_admin(
    x_admin_key: Optional[str]
):

    if not hmac.compare_digest(
        x_admin_key or "",
        ADMIN_KEY
    ):

        raise HTTPException(
            status_code=401,
            detail="Bad admin key"
        )


@app.post("/api/on")
async def turn_on(
    x_admin_key: Optional[str] =
    Header(default=None)
):

    require_admin(
        x_admin_key
    )

    set_server_enabled(
        True
    )

    return {
        "ok": True,
        "enabled": True
    }


@app.post("/api/off")
async def turn_off(
    x_admin_key: Optional[str] =
    Header(default=None)
):

    require_admin(
        x_admin_key
    )

    set_server_enabled(
        False
    )

    for ws in list(clients):

        try:

            await ws.close(
                code=1012,
                reason="Server turned off by admin"
            )

        except Exception:
            pass

        clients.discard(ws)

    return {
        "ok": True,
        "enabled": False
    }


if __name__ == "__main__":

    import uvicorn

    port = int(
        os.getenv(
            "PORT",
            "8000"
        )
    )

    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=port
    )
