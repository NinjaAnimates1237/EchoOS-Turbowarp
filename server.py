import json
import os
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse

app = FastAPI(title="Scratch WebSocket Server")

ADMIN_KEY = os.getenv("ADMIN_KEY", "change-me-now")
STATE_PATH = Path(os.getenv("STATE_PATH", "server_state.json"))


def load_enabled() -> bool:
    try:
        data = json.loads(STATE_PATH.read_text())
        return bool(data.get("enabled", True))
    except Exception:
        return True


def save_enabled(value: bool) -> None:
    STATE_PATH.write_text(json.dumps({"enabled": value}))


server_enabled = load_enabled()
active_connections: set[WebSocket] = set()


def check_admin_key(key: str | None) -> None:
    if not key or key != ADMIN_KEY:
        raise HTTPException(status_code=401, detail="Wrong admin key")


@app.get("/")
async def root():
    return {
        "name": "Scratch WebSocket Server",
        "enabled": server_enabled,
        "websocket": "/ws",
        "control_panel": "/control",
    }


@app.get("/status")
async def status():
    return {"enabled": server_enabled}


@app.get("/control", response_class=HTMLResponse)
async def control_panel():
    return """
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>WebSocket Control</title>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 540px; margin: 50px auto; padding: 0 18px; }
    input, button { font-size: 18px; padding: 10px; margin: 6px 0; }
    input { width: 100%; box-sizing: border-box; }
    button { margin-right: 8px; cursor: pointer; }
    #status { font-weight: 700; }
  </style>
</head>
<body>
  <h1>WebSocket Server Control</h1>
  <p>WebSocket status: <span id="status">checking...</span></p>
  <input id="key" type="password" placeholder="Admin key" />
  <div>
    <button onclick="setState('on')">Turn ON</button>
    <button onclick="setState('off')">Turn OFF</button>
  </div>
  <p id="message"></p>
<script>
async function refresh() {
  const r = await fetch('/status');
  const d = await r.json();
  document.getElementById('status').textContent = d.enabled ? 'ON' : 'OFF';
}
async function setState(which) {
  const key = document.getElementById('key').value;
  const r = await fetch('/admin/' + which, {
    method: 'POST',
    headers: {'X-Admin-Key': key}
  });
  const msg = document.getElementById('message');
  if (!r.ok) {
    msg.textContent = 'Wrong admin key or request failed.';
    return;
  }
  const d = await r.json();
  msg.textContent = 'Server is now ' + (d.enabled ? 'ON' : 'OFF') + '.';
  refresh();
}
refresh();
</script>
</body>
</html>
"""


@app.post("/admin/on")
async def admin_on(x_admin_key: str | None = Header(default=None)):
    global server_enabled
    check_admin_key(x_admin_key)
    server_enabled = True
    save_enabled(True)
    return {"enabled": True}


@app.post("/admin/off")
async def admin_off(x_admin_key: str | None = Header(default=None)):
    global server_enabled
    check_admin_key(x_admin_key)
    server_enabled = False
    save_enabled(False)

    # Immediately disconnect clients that are already connected.
    for client in list(active_connections):
        try:
            await client.send_text("SERVER_OFF")
            await client.close(code=1012)
        except Exception:
            pass
    active_connections.clear()

    return {"enabled": False}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()

    if not server_enabled:
        await ws.send_text("SERVER_OFF")
        await ws.close(code=1013)
        return

    active_connections.add(ws)
    await ws.send_text("CONNECTED")

    try:
        while True:
            message = await ws.receive_text()

            # A simple keepalive message you can send from Scratch/TurboWarp.
            if message.lower() == "ping":
                await ws.send_text("pong")
            else:
                # Do not print or store message contents, because one of your
                # Scratch messages might be a password.
                await ws.send_text("OK")

    except WebSocketDisconnect:
        pass
    finally:
        active_connections.discard(ws)


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("server:app", host="0.0.0.0", port=port)
