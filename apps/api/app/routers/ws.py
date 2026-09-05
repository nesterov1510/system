"""WebSocket-эндпоинт для realtime-событий (чат, статусы ремонтов).

Токен передаётся в query-параметре, поэтому здесь ОБЯЗАТЕЛЬНА та же проверка
типа токена, что и в REST-слое (`core.deps.get_current_user`): иначе
долговременный refresh-токен открывал live-соединение вместо 30-минутного
access-токена.
"""
import uuid

import jwt
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.security import decode_token
from app.db.models import User
from app.db.session import async_session_factory
from app.ws.manager import manager

router = APIRouter(tags=["ws"])

# Код закрытия, который понимает клиент (см. apps/web/lib/chatSocket.ts).
CLOSE_UNAUTHORIZED = 4401


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str | None = None):
    if not token:
        await websocket.close(code=CLOSE_UNAUTHORIZED)
        return

    # 1. Подпись и тип токена. Принимаем ТОЛЬКО access-токены.
    try:
        payload = decode_token(token)
    except jwt.PyJWTError:
        await websocket.close(code=CLOSE_UNAUTHORIZED)
        return

    if payload.get("type") != "access":
        await websocket.close(code=CLOSE_UNAUTHORIZED)
        return

    # 2. Субъект должен быть валидным UUID (некорректный токен -> 500 в логах
    #    быть не должно).
    raw_sub = payload.get("sub")
    try:
        user_id = uuid.UUID(str(raw_sub))
    except (TypeError, ValueError):
        await websocket.close(code=CLOSE_UNAUTHORIZED)
        return

    # 3. Пользователь существует и активен.
    async with async_session_factory() as db:
        user = await db.get(User, user_id)
        if user is None or not user.active:
            await websocket.close(code=CLOSE_UNAUTHORIZED)
            return
        user_name = user.name

    await manager.connect(user_id, websocket)
    try:
        await websocket.send_json(
            {"type": "hello", "user": {"id": str(user_id), "name": user_name}}
        )
        while True:
            # Держим соединение; входящие события (typing/read) обрабатываются
            # через REST. Здесь достаточно не дать сокету закрыться по таймауту.
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(user_id, websocket)
    except Exception:  # noqa: BLE001 — соединение рвётся, менеджер чистим
        manager.disconnect(user_id, websocket)
