import uuid

import jwt
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.security import decode_token
from app.db.session import async_session_factory
from app.db.models import User
from app.ws.manager import manager

router = APIRouter(tags=["ws"])


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str | None = None):
    if not token:
        await websocket.close(code=4401)
        return

    try:
        payload = decode_token(token)
    except jwt.PyJWTError:
        await websocket.close(code=4401)
        return

    user_id = uuid.UUID(payload["sub"])
    async with async_session_factory() as db:
        user = await db.get(User, user_id)
        if user is None or not user.active:
            await websocket.close(code=4401)
            return

    await manager.connect(user_id, websocket)
    try:
        await websocket.send_json(
            {"type": "hello", "user": {"id": str(user_id), "name": user.name}}
        )
        while True:
            # We accept keep-alive pings; inbound events handled later (typing, read).
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(user_id, websocket)
    except Exception:
        manager.disconnect(user_id, websocket)
