import os
import re
import asyncio
import sqlite3
import hashlib
import secrets
import hmac
from datetime import datetime, timezone

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Header, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse


app = FastAPI()

# ==========================================
# SETTINGS
# ==========================================

DATABASE_FILE = "data.db"

ADMIN_KEY = os.getenv(
    "ADMIN_KEY",
    "change-this-password"
)

clients = set()


# ==========================================
# DATABASE
# ==========================================

def get_db():
    connection = sqlite3.connect(
        DATABASE_FILE,
        check_same_thread=False
    )

    connection.row_factory = sqlite3.Row

    return connection


def setup_database():

    db = get_db()

    cursor = db.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_info (
            user_id TEXT NOT NULL,
            info_key TEXT NOT NULL,
            info_value TEXT NOT NULL,

            PRIMARY KEY (
                user_id,
                info_key
            )
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    cursor.execute("""
        INSERT OR IGNORE INTO settings
        (key, value)

        VALUES
        ('server_enabled', '1')
    """)

    db.commit()

    db.close()


@app.on_event("startup")
async def startup():

    setup_database()


# ==========================================
# PASSWORDS
# ==========================================

def hash_password(password):

    salt = secrets.token_hex(16)

    hashed = hashlib.sha256(
        (
            salt
            +
            password
        ).encode()
    ).hexdigest()

    return (
        salt
        +
        ":"
        +
        hashed
    )


def check_password(
    password,
    stored
):

    try:

        salt, old_hash = stored.split(
            ":",
            1
        )

        new_hash = hashlib.sha256(
            (
                salt
                +
                password
            ).encode()
        ).hexdigest()

        return hmac.compare_digest(
            new_hash,
            old_hash
        )

    except Exception:

        return False


# ==========================================
# SERVER ON/OFF
# ==========================================

def is_server_enabled():

    db = get_db()

    cursor = db.cursor()

    cursor.execute("""
        SELECT value
        FROM settings
        WHERE key = 'server_enabled'
    """)

    result = cursor.fetchone()

    db.close()

    if result is None:
        return True

    return result["value"] == "1"


def set_server_enabled(enabled):

    db = get_db()

    cursor = db.cursor()

    value = (
        "1"
        if enabled
        else
        "0"
    )

    cursor.execute("""
        INSERT INTO settings
        (key, value)

        VALUES
        ('server_enabled', ?)

        ON CONFLICT(key)

        DO UPDATE SET
        value = excluded.value
    """, (value,))

    db.commit()

    db.close()


# ==========================================
# USER FUNCTIONS
# ==========================================

def register_user(
    username,
    password,
    user_id
):

    username = username.strip()
    password = password.strip()
    user_id = user_id.strip()

    if not username:
        return "REGISTER_ERROR:NO_USERNAME"

    if not password:
        return "REGISTER_ERROR:NO_PASSWORD"

    if not user_id:
        return "REGISTER_ERROR:NO_ID"

    db = get_db()

    cursor = db.cursor()

    # Check ID
    cursor.execute(
        """
        SELECT id
        FROM users
        WHERE id = ?
        """,
        (user_id,)
    )

    if cursor.fetchone():

        db.close()

        return "REGISTER_ERROR:ID_EXISTS"

    # Check username
    cursor.execute(
        """
        SELECT username
        FROM users
        WHERE username = ?
        """,
        (username,)
    )

    if cursor.fetchone():

        db.close()

        return "REGISTER_ERROR:USERNAME_EXISTS"

    password_hash = hash_password(
        password
    )

    created_at = datetime.now(
        timezone.utc
    ).isoformat()

    cursor.execute(
        """
        INSERT INTO users
        (
            id,
            username,
            password_hash,
            created_at
        )

        VALUES (?, ?, ?, ?)
        """,
        (
            user_id,
            username,
            password_hash,
            created_at
        )
    )

    db.commit()

    db.close()

    return "REGISTERED"


def login_user(
    username,
    password
):

    db = get_db()

    cursor = db.cursor()

    cursor.execute(
        """
        SELECT *
        FROM users
        WHERE username = ?
        """,
        (username,)
    )

    user = cursor.fetchone()

    db.close()

    if user is None:

        return "LOGIN_ERROR"

    if check_password(
        password,
        user["password_hash"]
    ):

        return (
            "LOGIN_OK:"
            +
            user["id"]
        )

    return "LOGIN_ERROR"


# ==========================================
# STORE EXTRA INFO
# ==========================================

def set_user_info(
    user_id,
    key,
    value
):

    user_id = user_id.strip()
    key = key.strip()
    value = value.strip()

    if key.lower() in [
        "password",
        "password_hash"
    ]:

        return "SETINFO_ERROR:INVALID_KEY"

    db = get_db()

    cursor = db.cursor()

    cursor.execute(
        """
        SELECT id
        FROM users
        WHERE id = ?
        """,
        (user_id,)
    )

    if cursor.fetchone() is None:

        db.close()

        return "SETINFO_ERROR:USER_NOT_FOUND"

    cursor.execute(
        """
        INSERT INTO user_info
        (
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
            value
        )
    )

    db.commit()

    db.close()

    return "SETINFO_OK"


# ==========================================
# GET USER
# ==========================================

def get_user(identifier):

    identifier = identifier.strip()

    db = get_db()

    cursor = db.cursor()

    cursor.execute(
        """
        SELECT
            id,
            username,
            created_at

        FROM users

        WHERE
            id = ?
            OR
            username = ?
        """,
        (
            identifier,
            identifier
        )
    )

    user = cursor.fetchone()

    if user is None:

        db.close()

        return None

    cursor.execute(
        """
        SELECT
            info_key,
            info_value

        FROM user_info

        WHERE user_id = ?

        ORDER BY info_key
        """,
        (
            user["id"],
        )
    )

    extra_info = cursor.fetchall()

    result = {
        "username": user["username"],
        "id": user["id"],
        "created_at": user["created_at"]
    }

    for item in extra_info:

        result[
            item["info_key"]
        ] = item["info_value"]

    db.close()

    return result


# ==========================================
# SEND USER ONE MESSAGE AT A TIME
# ==========================================

async def send_user(
    websocket,
    identifier
):

    user = get_user(
        identifier
    )

    if user is None:

        await websocket.send_text(
            "USER_NOT_FOUND"
        )

        return

    await websocket.send_text(
        "BEGIN_USER"
    )

    await asyncio.sleep(
        0.1
    )

    for key, value in user.items():

        await websocket.send_text(
            str(key)
            +
            ":"
            +
            str(value)
        )

        await asyncio.sleep(
            0.1
        )

    await websocket.send_text(
        "END_USER"
    )


# ==========================================
# WEBSOCKET
#
# BOTH URLS WORK:
#
# wss://server.onrender.com
# wss://server.onrender.com/ws
# ==========================================

@app.websocket("/")
@app.websocket("/ws")
async def websocket_server(
    websocket: WebSocket
):

    # If server manually turned off
    if not is_server_enabled():

        await websocket.accept()

        await websocket.send_text(
            "SERVER_OFF"
        )

        await websocket.close()

        return

    await websocket.accept()

    clients.add(
        websocket
    )

    try:

        await websocket.send_text(
            "CONNECTED"
        )

        while True:

            message = await websocket.receive_text()

            message = message.strip()

            if not message:
                continue

            lower = message.lower()

            # ==================================
            # PING
            # ==================================

            if lower == "ping":

                await websocket.send_text(
                    "pong"
                )

                continue


            # ==================================
            # GetUserID(12345)
            # ==================================

            match = re.fullmatch(
                r"(?i)getuserid\s*\(\s*(.*?)\s*\)",
                message
            )

            if match:

                identifier = match.group(
                    1
                )

                await send_user(
                    websocket,
                    identifier
                )

                continue


            # ==================================
            # GetUserID
            #
            # then send ID
            # ==================================

            if lower == "getuserid":

                await websocket.send_text(
                    "SEND_ID"
                )

                identifier = await websocket.receive_text()

                await send_user(
                    websocket,
                    identifier
                )

                continue


            # ==================================
            # SetInfo(ID,key,value)
            #
            # Example:
            #
            # SetInfo(12345,coins,500)
            # ==================================

            match = re.fullmatch(
                r"(?i)setinfo\s*\((.*?),(.*?),(.*?)\)",
                message
            )

            if match:

                user_id = match.group(
                    1
                ).strip()

                key = match.group(
                    2
                ).strip()

                value = match.group(
                    3
                ).strip()

                response = set_user_info(
                    user_id,
                    key,
                    value
                )

                await websocket.send_text(
                    response
                )

                continue


            # ==================================
            # LOGIN(username,password)
            # ==================================

            match = re.fullmatch(
                r"(?i)login\s*\((.*?),(.*?)\)",
                message
            )

            if match:

                username = match.group(
                    1
                ).strip()

                password = match.group(
                    2
                ).strip()

                response = login_user(
                    username,
                    password
                )

                await websocket.send_text(
                    response
                )

                continue


            # ==================================
            # YOUR CURRENT SCRATCH REGISTER
            #
            # Message 1 = USERNAME
            # Message 2 = PASSWORD
            # Message 3 = ID
            #
            # No "register" command required.
            # ==================================

            username = message

            password = await websocket.receive_text()

            user_id = await websocket.receive_text()

            result = register_user(
                username,
                password,
                user_id
            )

            await websocket.send_text(
                result
            )


    except WebSocketDisconnect:

        pass

    except Exception as error:

        print(
            "WebSocket error:",
            error
        )

        try:

            await websocket.send_text(
                "SERVER_ERROR"
            )

        except Exception:

            pass

    finally:

        clients.discard(
            websocket
        )


# ==========================================
# NORMAL WEBSITE
# ==========================================

@app.get("/")
async def homepage():

    return JSONResponse({
        "server": "EchoOS WebSocket Server",
        "status": (
            "ON"
            if is_server_enabled()
            else
            "OFF"
        ),
        "websocket_paths": [
            "/",
            "/ws"
        ],
        "connected_clients": len(
            clients
        )
    })


# ==========================================
# CONTROL WEBSITE
# ==========================================

CONTROL_PAGE = """
<!DOCTYPE html>

<html>

<head>

<title>EchoOS Server</title>

<style>

body {
    background: #111;
    color: white;
    font-family: Arial;
    text-align: center;
    margin-top: 80px;
}

button {
    padding: 15px 30px;
    margin: 10px;
    font-size: 20px;
    cursor: pointer;
}

input {
    padding: 12px;
    font-size: 18px;
}

#status {
    font-size: 24px;
    margin: 25px;
}

</style>

</head>

<body>

<h1>
EchoOS WebSocket Server
</h1>

<div id="status">
Checking...
</div>

<input
    id="admin"
    type="password"
    placeholder="Admin key"
/>

<br>

<button onclick="turnOn()">
Turn ON
</button>

<button onclick="turnOff()">
Turn OFF
</button>

<script>

async function updateStatus() {

    const response =
        await fetch("/api/status");

    const data =
        await response.json();

    document.getElementById(
        "status"
    ).innerText =
        data.enabled
        ? "SERVER ON"
        : "SERVER OFF";
}


async function turnOn() {

    const key =
        document.getElementById(
            "admin"
        ).value;

    await fetch(
        "/api/on",
        {
            method: "POST",

            headers: {
                "X-Admin-Key": key
            }
        }
    );

    updateStatus();
}


async function turnOff() {

    const key =
        document.getElementById(
            "admin"
        ).value;

    await fetch(
        "/api/off",
        {
            method: "POST",

            headers: {
                "X-Admin-Key": key
            }
        }
    );

    updateStatus();
}


updateStatus();

</script>

</body>

</html>
"""


@app.get(
    "/control",
    response_class=HTMLResponse
)
async def control_page():

    return CONTROL_PAGE


# ==========================================
# STATUS API
# ==========================================

@app.get("/api/status")
async def status():

    return {
        "enabled": is_server_enabled(),
        "clients": len(clients)
    }


# ==========================================
# ADMIN AUTH
# ==========================================

def verify_admin(key):

    if not hmac.compare_digest(
        key or "",
        ADMIN_KEY
    ):

        raise HTTPException(
            status_code=401,
            detail="Wrong admin key"
        )


# ==========================================
# TURN SERVER ON
# ==========================================

@app.post("/api/on")
async def server_on(
    x_admin_key: str = Header(
        default=""
    )
):

    verify_admin(
        x_admin_key
    )

    set_server_enabled(
        True
    )

    return {
        "success": True,
        "enabled": True
    }


# ==========================================
# TURN SERVER OFF
# ==========================================

@app.post("/api/off")
async def server_off(
    x_admin_key: str = Header(
        default=""
    )
):

    verify_admin(
        x_admin_key
    )

    set_server_enabled(
        False
    )

    # Disconnect everyone
    for websocket in list(
        clients
    ):

        try:

            await websocket.send_text(
                "SERVER_OFF"
            )

            await websocket.close()

        except Exception:

            pass

        clients.discard(
            websocket
        )

    return {
        "success": True,
        "enabled": False
    }


# ==========================================
# RUN LOCALLY
# ==========================================

if __name__ == "__main__":

    import uvicorn

    port = int(
        os.getenv(
            "PORT",
            8000
        )
    )

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port
    )
