from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from typing import Dict, Set

from fastapi import WebSocket

from app.auth.jwt_handler import decode_access_token

logger = logging.getLogger(__name__)


def _extract_ws_user_id(websocket: WebSocket) -> int | None:
    """Shared WebSocket auth helper — mirrors app.ws.gateway._ws_auth.

    Token resolution order:
      1. Query param  ?token=...
      2. Authorization: Bearer ...
    """
    token = websocket.query_params.get("token")
    if not token:
        auth = websocket.headers.get("authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    if not token:
        return None
    payload = decode_access_token(token)
    if not payload:
        return None
    try:
        return int(payload["sub"])
    except (KeyError, ValueError):
        return None


class SyncDocument:
    """Holds a document's state and its subscribers."""

    def __init__(self, doc_id: str):
        self.doc_id = doc_id
        self.state: dict = {}
        self.version: int = 0
        self.subscribers: Set[WebSocket] = set()

    def apply_update(self, update: dict, source_ws: WebSocket | None = None):
        """Merge update into document state and broadcast to subscribers."""
        for key, value in update.items():
            if value is None:
                self.state.pop(key, None)
            else:
                self.state[key] = value
        self.version += 1

        message = json.dumps({
            "type": "sync_update",
            "doc_id": self.doc_id,
            "update": update,
            "version": self.version,
        })

        for ws in list(self.subscribers):
            if ws is source_ws:
                continue
            try:
                asyncio.get_event_loop().create_task(
                    self._safe_send(ws, message, self.subscribers)
                )
            except RuntimeError:
                self.subscribers.discard(ws)
                logger.warning(f"Removed disconnected subscriber from doc {self.doc_id}")

    async def _safe_send(self, ws: WebSocket, message: str, subscribers: set):
        try:
            await ws.send_text(message)
        except Exception as exc:
            subscribers.discard(ws)
            logger.warning(f"WebSocket send failed, removing subscriber: {exc}")


class SyncManager:
    """Manages sync documents and WebSocket connections."""

    def __init__(self):
        self.documents: Dict[str, SyncDocument] = defaultdict(lambda: SyncDocument(""))
        self._lock = asyncio.Lock()

    def get_or_create(self, doc_id: str) -> SyncDocument:
        if doc_id not in self.documents:
            doc = SyncDocument(doc_id)
            self.documents[doc_id] = doc
        return self.documents[doc_id]

    async def handle_connection(self, websocket: WebSocket):
        """Handle a sync WebSocket connection (JWT-authenticated)."""
        user_id = _extract_ws_user_id(websocket)
        if user_id is None:
            await websocket.close(code=4001, reason="Authentication required")
            return
        await websocket.accept()
        subscribed_docs: Set[str] = set()

        try:
            while True:
                data = await websocket.receive_text()
                message = json.loads(data)
                msg_type = message.get("type", "")

                if msg_type == "subscribe":
                    doc_id = message["doc_id"]
                    doc = self.get_or_create(doc_id)
                    doc.subscribers.add(websocket)
                    subscribed_docs.add(doc_id)

                    await websocket.send_text(json.dumps({
                        "type": "sync_full",
                        "doc_id": doc_id,
                        "state": doc.state,
                        "version": doc.version,
                    }))

                elif msg_type == "sync_update":
                    doc_id = message["doc_id"]
                    update = message.get("update", {})
                    if doc_id in subscribed_docs:
                        doc = self.documents.get(doc_id)
                        if doc:
                            doc.apply_update(update, source_ws=websocket)

                elif msg_type == "unsubscribe":
                    doc_id = message["doc_id"]
                    if doc_id in self.documents:
                        self.documents[doc_id].subscribers.discard(websocket)
                    subscribed_docs.discard(doc_id)

                elif msg_type == "get_state":
                    doc_id = message["doc_id"]
                    doc = self.documents.get(doc_id)
                    if doc:
                        await websocket.send_text(json.dumps({
                            "type": "sync_full",
                            "doc_id": doc_id,
                            "state": doc.state,
                            "version": doc.version,
                        }))

        except Exception as e:
            logger.info(f"Sync WebSocket disconnected: {e}")
        finally:
            for doc_id in subscribed_docs:
                if doc_id in self.documents:
                    self.documents[doc_id].subscribers.discard(websocket)


sync_manager = SyncManager()
