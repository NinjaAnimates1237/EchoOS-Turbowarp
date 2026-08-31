import asyncio
import json
import os
from collections import defaultdict
from typing import Dict, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

app = FastAPI(title="PixAttach Server", version="0.1.0")

# project_id -> {"project": set[WebSocket], "controller": set[WebSocket]}
rooms: Dict[str, Dict[str, Set[WebSocket]]] = defaultdict(
    lambda: {"project": set(), "controller": set()}
)

# Cloud-like Pix Vars kept for each project while the server is running.
pix_variables: Dict[str, dict] = defaultdict(dict)


def configured_tokens() -> Dict[str, str]:
    """Read optional per-project tokens from a JSON environment variable."""
    raw = os.getenv("PIXATTACH_PROJECT_TOKENS", "{}")
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}


def token_is_valid(project_id: str, supplied_token: str) -> bool:
    project_tokens = configured_tokens()
    expected = project_tokens.get(project_id)

    if expected is None:
        expected = os.getenv("PIXATTACH_TOKEN", "development-token")

    return bool(supplied_token) and supplied_token == expected


async def send_json_safe(socket: WebSocket, packet: dict) -> bool:
    try:
        await socket.send_json(packet)
        return True
    except Exception:
        return False


async def broadcast(project_id: str, destination: str, packet: dict) -> None:
    sockets = list(rooms[project_id][destination])
    if not sockets:
        return

    results = await asyncio.gather(
        *(send_json_safe(socket, packet) for socket in sockets),
        return_exceptions=True,
    )

    for socket, result in zip(sockets, results):
        if result is not True:
            rooms[project_id][destination].discard(socket)


def remove_socket(project_id: str, client_type: str, socket: WebSocket) -> None:
    room = rooms.get(project_id)
    if not room:
        return

    room[client_type].discard(socket)

    if not room["project"] and not room["controller"]:
        rooms.pop(project_id, None)


@app.get("/")
async def root():
    return {
        "name": "PixAttach",
        "status": "online",
        "version": "0.1.0",
        "connected_projects": len(rooms),
    }


@app.get("/health")
async def health():
    return {"ok": True}


@app.websocket("/ws")
async def websocket_endpoint(socket: WebSocket):
    await socket.accept()
    project_id = ""
    client_type = ""

    try:
        first_packet = await asyncio.wait_for(socket.receive_json(), timeout=10)

        if first_packet.get("type") != "connect":
            await socket.send_json({"type": "error", "error": "connect_required"})
            await socket.close(code=1008)
            return

        project_id = str(first_packet.get("project_id", "")).strip()
        client_type = str(first_packet.get("client_type", "")).strip()
        token = str(first_packet.get("token", ""))

        if client_type not in {"project", "controller"}:
            await socket.send_json({"type": "error", "error": "invalid_client_type"})
            await socket.close(code=1008)
            return

        if not project_id or not token_is_valid(project_id, token):
            await socket.send_json({"type": "error", "error": "authentication_failed"})
            await socket.close(code=1008)
            return

        rooms[project_id][client_type].add(socket)

        await socket.send_json(
            {
                "type": "connected",
                "project_id": project_id,
                "client_type": client_type,
            }
        )

        if client_type == "project":
            await socket.send_json(
                {"type": "pix_variables", "variables": pix_variables[project_id]}
            )

        while True:
            packet = await socket.receive_json()
            packet_type = str(packet.get("type", ""))

            if packet_type == "ping":
                await socket.send_json({"type": "pong"})
                continue

            if client_type == "project" and packet_type == "set_pix_variable":
                name = str(packet.get("name", "")).strip()
                if not name or len(name) > 64:
                    await socket.send_json(
                        {"type": "error", "error": "invalid_pix_variable_name"}
                    )
                    continue
                value = packet.get("value", "")
                pix_variables[project_id][name] = value
                await broadcast(
                    project_id,
                    "project",
                    {"type": "pix_variable_changed", "name": name, "value": value},
                )
                continue

            if client_type == "project" and packet_type == "delete_pix_variable":
                name = str(packet.get("name", "")).strip()
                if name:
                    pix_variables[project_id].pop(name, None)
                    await broadcast(
                        project_id,
                        "project",
                        {"type": "pix_variable_deleted", "name": name},
                    )
                continue

            # Python controllers may ask the running project to do these things.
            if client_type == "controller" and packet_type in {
                "value",
                "set_variable",
                "get_variable",
            }:
                await broadcast(project_id, "project", packet)
                continue

            # Running projects send values and command responses to Python.
            if client_type == "project" and packet_type in {
                "value",
                "variable_value",
                "set_variable_result",
                "error",
            }:
                await broadcast(project_id, "controller", packet)
                continue

            await socket.send_json(
                {"type": "error", "error": "command_not_allowed", "command": packet_type}
            )

    except (WebSocketDisconnect, asyncio.TimeoutError):
        pass
    except Exception as error:
        try:
            await socket.send_json({"type": "error", "error": str(error)})
        except Exception:
            pass
    finally:
        if project_id and client_type:
            remove_socket(project_id, client_type, socket)
