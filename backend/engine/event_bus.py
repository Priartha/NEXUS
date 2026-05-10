from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any


Subscriber = Callable[[dict[str, Any]], Awaitable[None]]


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[Subscriber]] = defaultdict(list)

    def subscribe(self, topic: str, subscriber: Subscriber) -> None:
        self._subscribers[topic].append(subscriber)

    async def publish(self, topic: str, payload: dict[str, Any]) -> None:
        subscribers = list(self._subscribers.get(topic, []))
        if not subscribers:
            return
        await asyncio.gather(*(subscriber(payload) for subscriber in subscribers))

