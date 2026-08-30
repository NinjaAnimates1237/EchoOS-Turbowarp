import json
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

import websocket


class PixAttachError(Exception):
    pass


class Client:
    def __init__(self, project_id: str, server: str, token: str, timeout: float = 8):
        self.project_id = str(project_id)
        self.server = server
        self.token = token
        self.timeout = timeout
        self.socket: Optional[websocket.WebSocket] = None
        self.running = False
        self.callbacks: List[Callable[[Any], None]] = []
        self.pending: Dict[str, Dict[str, Any]] = {}
        self.lock = threading.Lock()
        self.receiver: Optional[threading.Thread] = None

    def connect(self):
        self.socket = websocket.create_connection(self.server, timeout=self.timeout)
        self.socket.send(
            json.dumps(
                {
                    "type": "connect",
                    "client_type": "controller",
                    "project_id": self.project_id,
                    "token": self.token,
                }
            )
        )

        packet = json.loads(self.socket.recv())
        if packet.get("type") != "connected":
            raise PixAttachError(packet.get("error", "Connection failed"))

        self.running = True
        self.receiver = threading.Thread(target=self._receive_loop, daemon=True)
        self.receiver.start()
        return self

    def close(self):
        self.running = False
        if self.socket:
            try:
                self.socket.close()
            finally:
                self.socket = None

    def _send(self, packet: dict):
        if not self.socket or not self.running:
            raise PixAttachError("PixAttach is not connected")
        with self.lock:
            self.socket.send(json.dumps(packet))

    def send(self, value: Any):
        self._send({"type": "value", "value": value})

    def set_var(self, name: str, value: Any, wait: bool = True):
        request_id = uuid.uuid4().hex
        waiter = self._make_waiter(request_id)
        self._send(
            {
                "type": "set_variable",
                "request_id": request_id,
                "name": name,
                "value": value,
            }
        )
        if not wait:
            return None
        packet = self._wait(request_id, waiter)
        if not packet.get("success"):
            raise PixAttachError(packet.get("error", "Variable change failed"))
        return True

    def get_var(self, name: str):
        request_id = uuid.uuid4().hex
        waiter = self._make_waiter(request_id)
        self._send(
            {"type": "get_variable", "request_id": request_id, "name": name}
        )
        packet = self._wait(request_id, waiter)
        if not packet.get("success"):
            raise PixAttachError(packet.get("error", "Could not read variable"))
        return packet.get("value")

    def on_value(self, callback=None):
        def register(function):
            self.callbacks.append(function)
            return function

        return register(callback) if callback else register

    def _make_waiter(self, request_id: str):
        waiter = {"event": threading.Event(), "packet": None}
        self.pending[request_id] = waiter
        return waiter

    def _wait(self, request_id: str, waiter: dict):
        if not waiter["event"].wait(self.timeout):
            self.pending.pop(request_id, None)
            raise PixAttachError("The project did not respond in time")
        return waiter["packet"]

    def _receive_loop(self):
        while self.running and self.socket:
            try:
                packet = json.loads(self.socket.recv())
            except Exception:
                self.running = False
                break

            request_id = packet.get("request_id")
            if request_id and request_id in self.pending:
                waiter = self.pending.pop(request_id)
                waiter["packet"] = packet
                waiter["event"].set()
                continue

            if packet.get("type") == "value":
                for callback in list(self.callbacks):
                    try:
                        callback(packet.get("value"))
                    except Exception:
                        pass


def connect(project_id: str, server: str, token: str, timeout: float = 8) -> Client:
    return Client(project_id, server, token, timeout).connect()

