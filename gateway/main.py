from contextlib import asynccontextmanager
import asyncio
import hashlib
import json
from datetime import datetime
from typing import Optional, Dict

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from config import config

app = FastAPI(title="Clairify Gateway")


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("=" * 70)
    print("Clairify Gateway")
    print("=" * 70)
    print(f"OpenClaw IP: {config.OPENCLAW_IP}")
    print(f"OpenClaw Port: {config.OPENCLAW_PORT}")
    print(f"Max Connections: {config.MAX_CONNECTIONS}")
    print(f"Keepalive Connections: {config.MAX_KEEPALIVE_CONNECTIONS}")
    print(f"WebSocket Heartbeat: {config.WS_HEARTBEAT_INTERVAL}s")
    print("HTTP/2: Enabled")
    print("=" * 70)

    # Initialize HTTP client
    await openclaw_client.initialize()

    # Authenticate
    auth_success = await openclaw_client.authenticate()

    if auth_success:
        openclaw_client.refresh_task = asyncio.create_task(
            openclaw_client.start_proactive_refresh()
        )
        print("Proactive token refresh started")
    else:
        print("Failed to authenticate with OpenClaw")

    # Start WebSocket heartbeat
    manager.heartbeat_task = asyncio.create_task(manager.start_heartbeat())
    print("WebSocket heartbeat started")

    yield

    print("Shutting down gateway...")

    await openclaw_client.close()

    if manager.heartbeat_task:
        manager.heartbeat_task.cancel()

    if openclaw_client.refresh_task:
        openclaw_client.refresh_task.cancel()


app = FastAPI(lifespan=lifespan)


class ChatRequest(BaseModel):
    model: str = "llama3.2"
    messages: list[dict]
    stream: bool = True


class OpenClawClient:
    """Singleton HTTP client with connection pooling and token management"""

    def __init__(self):
        self.client: Optional[httpx.AsyncClient] = None
        self.token: Optional[str] = None
        self.token_refreshed_at: Optional[datetime] = None
        self.refresh_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

    async def initialize(self):
        """Initialize HTTP client with connection pooling"""
        if self.client is None:
            self.client = httpx.AsyncClient(
                timeout=httpx.Timeout(config.OPENCLAW_TIMEOUT, connect=10.0),
                limits=httpx.Limits(
                    max_keepalive_connections=config.MAX_KEEPALIVE_CONNECTIONS,
                    max_connections=config.MAX_CONNECTIONS,
                    keepalive_expiry=30.0
                ),
                http2=True  # Enable HTTP/2 for multiplexing
            )
            print(f"HTTP client initialized (HTTP/2, {config.MAX_CONNECTIONS} max connections)")

    async def authenticate(self, force_refresh: bool = False) -> bool:
        """Authenticate with OpenClaw and get token"""
        async with self._lock:
            if self.token and not force_refresh:
                return True

            if not config.OPENCLAW_IP:
                print("OPENCLAW_IP not configured")
                return False

            openclaw_url = f"http://{config.OPENCLAW_IP}:{config.OPENCLAW_PORT}"
            print(f"Authenticating with OpenClaw at {openclaw_url}")

            try:
                response = await self.client.post(
                    f"{openclaw_url}/api/v1/auths/signin",
                    json={
                        "email": config.OPENCLAW_EMAIL,
                        "password": config.OPENCLAW_PASSWORD,
                    },
                )

                if response.status_code == 200:
                    self.token = response.json().get("token")
                    self.token_refreshed_at = datetime.now()
                    print(f"Authenticated at {self.token_refreshed_at.strftime('%H:%M:%S')}")
                    return True
                else:
                    print(f"Auth failed: {response.status_code}")
                    return False

            except Exception as exc:
                print(f"Auth error: {exc}")
                return False

    async def start_proactive_refresh(self):
        """Background task to refresh token before expiry"""
        while True:
            await asyncio.sleep(config.TOKEN_REFRESH_INTERVAL)
            print(f"Proactive token refresh (interval: {config.TOKEN_REFRESH_INTERVAL}s)")
            await self.authenticate(force_refresh=True)

    async def get_available_models(self) -> list[str]:
        """Fetch available models from OpenClaw"""
        try:
            response = await self.client.get(
                f"http://{config.OPENCLAW_IP}:{config.OPENCLAW_PORT}/api/models",
                headers={"Authorization": f"Bearer {self.token}"}
            )

            if response.status_code == 200:
                data = response.json().get("data", [])
                return [model.get("id") for model in data if model.get("id")]
        except Exception as exc:
            print(f"Failed to fetch models: {exc}")

        return []

    async def close(self):
        """Cleanup resources"""
        if self.refresh_task:
            self.refresh_task.cancel()
        if self.client:
            await self.client.aclose()
            print("HTTP client closed")


# Global singleton
openclaw_client = OpenClawClient()


class ConnectionManager:
    """Manage active WebSocket connections"""

    def __init__(self):
        self.active_connections: Dict[str, dict] = {}
        self.heartbeat_task: Optional[asyncio.Task] = None

    def register(self, websocket: WebSocket, client_id: str, user_id: str):
        """Register WebSocket connection (already accepted)"""
        self.active_connections[client_id] = {
            "websocket": websocket,
            "user_id": user_id,
            "connected_at": datetime.now(),
            "last_ping": datetime.now()
        }
        print(f"WebSocket registered: {client_id} (user: {user_id})")
        print(f"  Active connections: {len(self.active_connections)}")

    def disconnect(self, client_id: str):
        """Unregister WebSocket connection"""
        if client_id in self.active_connections:
            user_id = self.active_connections[client_id]["user_id"]
            del self.active_connections[client_id]
            print(f"WebSocket disconnected: {client_id} (user: {user_id})")
            print(f"  Active connections: {len(self.active_connections)}")

    async def send_json(self, client_id: str, message: dict):
        """Send JSON message to client"""
        if client_id in self.active_connections:
            websocket = self.active_connections[client_id]["websocket"]
            await websocket.send_json(message)

    async def send_text(self, client_id: str, message: str):
        """Send text message to client"""
        if client_id in self.active_connections:
            websocket = self.active_connections[client_id]["websocket"]
            await websocket.send_text(message)

    async def start_heartbeat(self):
        """Send periodic pings to keep connections alive"""
        while True:
            await asyncio.sleep(config.WS_HEARTBEAT_INTERVAL)

            disconnected = []
            for client_id, conn in list(self.active_connections.items()):
                try:
                    await conn["websocket"].send_json({"type": "ping"})
                    conn["last_ping"] = datetime.now()
                except Exception as e:
                    print(f"Heartbeat failed for {client_id}: {e}")
                    disconnected.append(client_id)

            # Clean up dead connections
            for client_id in disconnected:
                self.disconnect(client_id)

            if self.active_connections:
                print(f"Heartbeat sent to {len(self.active_connections)} connections")


manager = ConnectionManager()


@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """WebSocket endpoint for real-time chat"""

    client_id = None

    try:
        # Accept connection ONCE
        await websocket.accept()
        print("WebSocket connection accepted, waiting for auth...")

        # PHASE 1: AUTHENTICATION
        try:
            auth_data = await asyncio.wait_for(websocket.receive_json(), timeout=10)
        except asyncio.TimeoutError:
            await websocket.send_json({"type": "error", "message": "Authentication timeout"})
            await websocket.close(code=1008)
            return

        token = auth_data.get("token")

        if not token:
            await websocket.send_json({"type": "error", "message": "Missing token"})
            await websocket.close(code=1008)
            return

        # Simple token validation (in production need validate against backend)
        user_id = auth_data.get("user_id", "unknown")
        client_id = hashlib.md5(f"{token}{user_id}".encode()).hexdigest()[:12]

        # Register connection (don't accept again)
        manager.register(websocket, client_id, user_id)

        # Send authentication success
        await websocket.send_json({
            "type": "authenticated",
            "client_id": client_id,
            "user_id": user_id,
            "message": "WebSocket connection established"
        })

        print(f"Client {client_id} authenticated as {user_id}")

        # PHASE 2: MESSAGE HANDLING LOOP
        while True:
            try:
                data = await websocket.receive_json()
            except Exception as e:
                print(f"Error receiving message from {client_id}: {e}")
                break

            # Handle ping/pong
            if data.get("type") == "pong":
                manager.active_connections[client_id]["last_ping"] = datetime.now()
                continue

            # Handle chat request
            if data.get("type") == "chat" or "messages" in data:
                await handle_chat_request(websocket, client_id, data)

            # Handle model list request
            elif data.get("type") == "get_models":
                models = await openclaw_client.get_available_models()
                await websocket.send_json({
                    "type": "models",
                    "models": models
                })

            else:
                await websocket.send_json({
                    "type": "error",
                    "message": f"Unknown message type: {data.get('type')}"
                })

    except WebSocketDisconnect:
        print(f"WebSocket disconnected normally: {client_id}")
    except Exception as exc:
        print(f"WebSocket error for {client_id}: {exc}")
        import traceback
        traceback.print_exc()
    finally:
        if client_id:
            manager.disconnect(client_id)


async def handle_chat_request(websocket: WebSocket, client_id: str, data: dict):
    """Handle chat request and stream response"""

    try:
        # Parse request
        request = ChatRequest(
            model=data.get("model", "llama3.2"),
            messages=data.get("messages", []),
            stream=True  # Always stream
        )

        print(f"Chat request from {client_id}: model={request.model}")

        # Send acknowledgment
        await websocket.send_json({
            "type": "chat_start",
            "model": request.model
        })

        # Forward to OpenClaw with streaming
        openclaw_url = f"http://{config.OPENCLAW_IP}:{config.OPENCLAW_PORT}/api/chat/completions"

        headers = {}
        if openclaw_client.token:
            headers["Authorization"] = f"Bearer {openclaw_client.token}"

        response = await openclaw_client.client.post(
            openclaw_url,
            json=request.model_dump(),
            headers=headers,
        )

        # Handle 401 (token expired)
        if response.status_code == 401:
            print(f"Token expired, refreshing for {client_id}...")
            await openclaw_client.authenticate(force_refresh=True)

            # Retry with new token
            headers["Authorization"] = f"Bearer {openclaw_client.token}"
            response = await openclaw_client.client.post(
                openclaw_url,
                json=request.model_dump(),
                headers=headers,
            )

        # Handle 400 (model not found)
        if response.status_code == 400 and "Model not found" in response.text:
            models = await openclaw_client.get_available_models()
            if models:
                fallback_model = models[0]
                print(f"Model '{request.model}' not found, using '{fallback_model}'")

                request.model = fallback_model
                response = await openclaw_client.client.post(
                    openclaw_url,
                    json=request.model_dump(),
                    headers=headers,
                )

        # Handle error responses
        if response.status_code != 200:
            await websocket.send_json({
                "type": "error",
                "message": f"OpenClaw error: {response.status_code}",
                "detail": response.text[:200]
            })
            return

        # Stream response chunks
        full_response = ""
        async for line in response.aiter_lines():
            if not line.strip():
                continue

            # Forward SSE chunks to WebSocket
            if line.startswith("data: "):
                try:
                    chunk_data = json.loads(line[6:])

                    # Check if done
                    if chunk_data.get("done"):
                        break

                    # Extract content
                    choices = chunk_data.get("choices", [])
                    if choices:
                        delta = choices[0].get("delta", {})
                        content = delta.get("content", "")

                        if content:
                            full_response += content

                            # Send chunk to client
                            await websocket.send_json({
                                "type": "chat_chunk",
                                "content": content
                            })

                except json.JSONDecodeError:
                    continue

        # Send completion
        await websocket.send_json({
            "type": "chat_end",
            "full_response": full_response,
            "length": len(full_response)
        })

        print(f"Chat completed for {client_id} ({len(full_response)} chars)")

    except httpx.TimeoutException:
        await websocket.send_json({
            "type": "error",
            "message": "Request timeout"
        })
    except httpx.ConnectError as exc:
        await websocket.send_json({
            "type": "error",
            "message": f"Cannot connect to OpenClaw: {exc}"
        })
    except Exception as exc:
        print(f"Error in handle_chat_request: {exc}")
        import traceback
        traceback.print_exc()
        await websocket.send_json({
            "type": "error",
            "message": f"Unexpected error: {exc}"
        })


@app.get("/health")
async def health():
    """Health check endpoint"""
    openclaw_reachable = False

    if config.OPENCLAW_IP and openclaw_client.client:
        try:
            response = await openclaw_client.client.get(
                f"http://{config.OPENCLAW_IP}:{config.OPENCLAW_PORT}/",
                timeout=5
            )
            openclaw_reachable = response.status_code == 200
        except Exception:
            pass

    return {
        "service": "Gateway",
        "status": "healthy",
        "openclaw_ip": config.OPENCLAW_IP,
        "openclaw_reachable": openclaw_reachable,
        "openclaw_authenticated": openclaw_client.token is not None,
        "token_refreshed_at": openclaw_client.token_refreshed_at.isoformat() if openclaw_client.token_refreshed_at else None,
        "active_websockets": len(manager.active_connections),
        "optimizations": [
            "HTTP/2 Connection Pooling",
            "WebSocket Streaming",
            "Proactive Token Refresh",
            "Persistent Connections"
        ]
    }


@app.get("/")
async def root():
    return {
        "service": "Clairify Gateway",
        "version": "1.0.0",
        "protocol": "WebSocket",
        "openclaw_ip": config.OPENCLAW_IP,
        "endpoints": {
            "chat": "WS /ws/chat",
            "health": "GET /health"
        },
        "active_connections": len(manager.active_connections)
    }
