# PixAttach

PixAttach connects Python programs to Gandi IDE and TurboWarp projects through
a small unsandboxed extension and a WebSocket server.

## Repository structure

- `pixattach.js` — project extension (copy the root extension file here)
- `server/` — FastAPI WebSocket relay server
- `python/` — installable Python client
- `example.py` — controller example

## Local server

```bash
cd server
python -m pip install -r requirements.txt
export PIXATTACH_TOKEN=development-token
uvicorn main:app --reload
```

The local WebSocket URL is `ws://localhost:8000/ws`.

## Install the Python client

From the repository root:

```bash
python -m pip install -e ./python
```

## Gandi project

Create global variables such as `ServerStatus`, then run:

```text
when green flag clicked
expose variable [ServerStatus]
connect to PixAttach [ws://localhost:8000/ws] project [echo-os] token [development-token]
```

Only exposed variables can be read or changed remotely.

## Render

Create a new Blueprint on Render using `render.yaml`. After deployment, copy
the generated `PIXATTACH_TOKEN` from the service environment and use the same
token in the project and Python client. The WebSocket URL will resemble:

`wss://pixattach-server.onrender.com/ws`

Do not commit a permanent production token into a public project. This first
version is intended for private development and testing.
