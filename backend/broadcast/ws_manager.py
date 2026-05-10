from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import WebSocket

from backend.models.types import to_wire


class ConnectionManager:
    def __init__(self) -> None:
        self._active: dict[WebSocket, str] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, timeframe: str) -> None:
        await websocket.accept()
        async with self._lock:
            self._active[websocket] = timeframe

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._active.pop(websocket, None)

    async def broadcast(self, data: dict[str, Any], timeframe: str | None = None) -> None:
        message = json.dumps(to_wire(data), separators=(",", ":"))
        async with self._lock:
            sockets = [
                websocket
                for websocket, subscribed_timeframe in self._active.items()
                if timeframe is None or subscribed_timeframe == timeframe
            ]

        async def _send(websocket: WebSocket) -> tuple[WebSocket, bool]:
            try:
                await asyncio.wait_for(websocket.send_text(message), timeout=3)
                return websocket, True
            except Exception:
                return websocket, False

        results = await asyncio.gather(*(_send(websocket) for websocket in sockets), return_exceptions=False)
        dead = [websocket for websocket, ok in results if not ok]

        if dead:
            async with self._lock:
                for websocket in dead:
                    self._active.pop(websocket, None)

    @property
    def count(self) -> int:
        return len(self._active)
