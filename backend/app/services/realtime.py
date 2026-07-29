from collections import deque

from fastapi import WebSocket


class RealtimeManager:
    def __init__(self, history_limit: int = 100) -> None:
        self.connections: list[WebSocket] = []
        self.history: deque[dict] = deque(maxlen=history_limit)

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.connections.append(websocket)
        for event in self.history:
            await websocket.send_json(event)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.connections:
            self.connections.remove(websocket)

    async def broadcast(self, event: dict) -> None:
        self.history.append(event)
        dead_connections: list[WebSocket] = []
        for connection in self.connections:
            try:
                await connection.send_json(event)
            except Exception:
                dead_connections.append(connection)

        for connection in dead_connections:
            self.disconnect(connection)


realtime_manager = RealtimeManager()
