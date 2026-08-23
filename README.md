# Free Scratch WebSocket Server

## WebSocket URL
After deployment, use:

`wss://YOUR-HOST/ws`

The server sends `CONNECTED` when a connection succeeds.
Send `ping` and it replies `pong`.
Other messages receive `OK`.

## ON / OFF control
Open:

`https://YOUR-HOST/control`

Enter the `ADMIN_KEY` from your hosting environment, then use **Turn ON** or **Turn OFF**.

When OFF, the web control panel still works, but `/ws` rejects clients with `SERVER_OFF`.

## Render
1. Put these files in a GitHub repository.
2. In Render, create a **Web Service** from the repo, or use the included `render.yaml`.
3. Set an `ADMIN_KEY` environment variable if Render did not generate one.
4. Use `wss://YOUR-SERVICE.onrender.com/ws` in Scratch/TurboWarp.

Important: Render's free web service can sleep after inactivity. It wakes on the next HTTP request or WebSocket connection.

## Oracle Cloud Always Free VM
For a more continuously running free server, run this project on an Always Free Linux VM.

Basic commands on the VM:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export ADMIN_KEY='choose-a-long-secret-key'
uvicorn server:app --host 0.0.0.0 --port 8000
```

For public `wss://`, place a TLS reverse proxy such as Caddy or Nginx in front of port 8000 and use a domain name.

The ON/OFF state is saved in `server_state.json` on hosts with persistent disk.
