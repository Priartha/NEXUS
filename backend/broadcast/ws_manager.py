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
                ws
                for ws, tf in self._active.items()
                if timeframe is None or tf == timeframe
            ]

        async def _send(ws: WebSocket) -> tuple[WebSocket, bool]:
            try:
                await asyncio.wait_for(ws.send_text(message), timeout=3)
                return ws, True
            except BaseException:
                return ws, False

        if not sockets:
            return
        raw = await asyncio.gather(*(_send(ws) for ws in sockets), return_exceptions=True)
        dead: list[WebSocket] = []
        for r in raw:
            if isinstance(r, tuple) and not r[1]:
                dead.append(r[0])

        if dead:
            async with self._lock:
                for ws in dead:
                    self._active.pop(ws, None)

    async def close_all(self) -> None:
        async with self._lock:
            sockets = list(self._active.keys())
            self._active.clear()
        for ws in sockets:
            try:
                await ws.close()
            except Exception:
                pass

    @property
    def count(self) -> int:
        return len(self._active)
