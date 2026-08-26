"""In-memory WebSocket connection manager (single-process MVP).

Fan-out to channels and direct user inboxes. Scales out later with Redis
pub/sub; the interface stays the same.
"""
import json
import uuid
from collections import defaultdict

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        # user_id -> set[WebSocket]
        self._user_sockets: dict[uuid.UUID, set[WebSocket]] = defaultdict(set)

    async def connect(self, user_id: uuid.UUID, ws: WebSocket) -> None:
        await ws.accept()
        self._user_sockets[user_id].add(ws)

    def disconnect(self, user_id: uuid.UUID, ws: WebSocket) -> None:
        self._user_sockets[user_id].discard(ws)
        if not self._user_sockets[user_id]:
            self._user_sockets.pop(user_id, None)

    async def send_to_user(self, user_id: uuid.UUID, event: dict) -> None:
        for ws in list(self._user_sockets.get(user_id, ())):
            try:
                await ws.send_text(json.dumps(event, ensure_ascii=False, default=str))
            except Exception:
                self.disconnect(user_id, ws)

    async def send_to_users(self, user_ids: list[uuid.UUID], event: dict) -> None:
        for uid in user_ids:
            await self.send_to_user(uid, event)

    async def broadcast(self, event: dict) -> None:
        for uid in list(self._user_sockets.keys()):
            await self.send_to_user(uid, event)


manager = ConnectionManager()
