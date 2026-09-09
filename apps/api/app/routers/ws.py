"""WebSocket-эндпоинт для realtime-событий (чат, статусы ремонтов).

Токен берётся из httpOnly-cookie (серверный веб-интерфейс на Jinja2) либо из
query-параметра `token` (обратная совместимость с API-клиентами/print-agent).

В ОБОИХ случаях обязательна та же проверка типа токена, что и в REST-слое
(`core.deps.get_current_user`): принимаем только access-токены, иначе
долговременный refresh-токен открывал бы live-соединение.
"""
import uuid

import jwt
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.security import decode_token
from app.db.models import User
from app.db.session import async_session_factory
from app.webui.deps import ACCESS_COOKIE
from app.ws.manager import manager

router = APIRouter(tags=["ws"])

# Код закрытия, который понимает клиент (см. webui/templates/chat.html).
CLOSE_UNAUTHORIZED = 4401


def _extract_token(websocket: WebSocket) -> str | None:
    """access-токен: сначала из cookie (серверный UI), затем из query (API)."""
    cookie_token = websocket.cookies.get(ACCESS_COOKIE)
    if cookie_token:
        return cookie_token
    return websocket.query_params.get("token")


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str | None = None):
    token = _extract_token(websocket)
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
