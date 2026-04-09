import httpx
import asyncio
import time
import sys
import json
import websockets

BACKEND_URL = "http://localhost:8000"
GATEWAY_WS_URL = "ws://localhost:8080/ws/chat"
LOGIN_PAYLOAD = {
    "user_id": "alice",
    "password": "pass1",
}
ACCESS_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0b2tlbl90eXBlIjoiYWNjZXNzIiwiZXhwIjoxNzc1NzUzMTg2LCJpYXQiOjE3NzU3NDk1ODYsImp0aSI6IjU4N2ZkYzY5NGY1ZDQ3YjlhNzA3ZDFjN2Y5MTY3YTNlIiwidXNlcl9pZCI6ImQ1MDgxMTAyLTRkZDEtNDE3Yy1iM2MyLTJiYTM1OGY3YmIyOSJ9.uZmH24AjynC7Cx524nYr-_twlM7fDr7nwZp8uSFk0co"
# we need to add this access token from webdev


def print_separator():
    print("\n" + "=" * 70)


def print_section(title):
    print("\n" + "─" * 70)
    print(f"  {title}")
    print("─" * 70)


async def test_websocket_chat():
    """WebSocket-based chat test"""

    print_separator()
    print("   CLAIRIFY CHAT POC - WebSocket Client")
    print("   Architecture: Client ←WebSocket→ Gateway → OpenClaw")
    print_separator()

    # AUTHENTICATION
    print_section("PHASE 1: Authentication")
    print(f"\n  Client → Backend ({BACKEND_URL})")

    start_time = time.time()

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{BACKEND_URL}/api/v1/auth/chat/",
                headers={
                    "Authorization": f"Bearer {ACCESS_TOKEN}"
                }
            )
    except httpx.ConnectError:
        print("\n  Cannot connect to backend")
        print("    Make sure backend is running: docker-compose ps")
        return
    except Exception as e:
        print(f"\n  Error: {e}")
        return

    if response.status_code != 200:
        print(f"\n  Authentication failed: {response.json()}")
        return

    auth_data = response.json().get("data")
    auth_time = round((time.time() - start_time) * 1000, 2)
    user = auth_data["user"]
    access_token = auth_data["access_token"]
    gateway_url = auth_data.get("gateway_url", "http://localhost:8080")
    gateway_ws_url = gateway_url.replace(
        "http://", "ws://").replace("https://", "wss://") + "/ws/chat"

    print(f"\n  Authenticated as: {user['user_name']}")
    print(f"  User ID: {user['user_id']}")
    print(f"  Username: {user['username']}")
    print(f"  Auth time: {auth_time}ms")
    print(f"  Access token: {access_token[:20]}...")

    # WEBSOCKET CONNECTION
    print_section("PHASE 2: WebSocket Connection")
    print(f"\n  Connecting to: {gateway_ws_url}")

    try:
        async with websockets.connect(gateway_ws_url) as websocket:
            print("  WebSocket connected")

            # Authenticate WebSocket
            await websocket.send(json.dumps({
                "token": access_token,
                "user_id": user["user_id"]
            }))

            # Wait for auth response
            auth_response = await websocket.recv()
            auth_result = json.loads(auth_response)

            if auth_result.get("type") == "error":
                print(f"\n  WebSocket auth failed: {auth_result.get('message')}")
                return

            if auth_result.get("type") == "authenticated":
                print("  WebSocket authenticated")
                print(f"  Client ID: {auth_result.get('client_id')}")

            # CHAT MESSAGES
            print_section("PHASE 3: Chat Messages (Streaming)")

            # Test messages
            messages = [
                "Hello! This is a test message.",
                "Can you tell me what you are in one short sentence?",
                "Thank you! Goodbye."
            ]

            for i, msg in enumerate(messages, 1):
                print(f"\n  ┌─ Message {i}/{len(messages)}")
                print("  │")
                print(f" │  You: {msg}")
                print("  │")

                start_time = time.time()
                first_chunk_time = None

                # Send chat request
                await websocket.send(json.dumps({
                    "type": "chat",
                    "model": "tinyllama:latest",
                    "messages": [{"role": "user", "content": msg}]
                }))

                print("  │  OpenClaw: ", end="", flush=True)

                full_response = ""

                # Receive streaming response
                while True:
                    try:
                        chunk = await asyncio.wait_for(websocket.recv(), timeout=60)

                        if first_chunk_time is None:
                            first_chunk_time = time.time()

                        data = json.loads(chunk)

                        # Handle different message types
                        if data.get("type") == "ping":
                            # Respond to heartbeat
                            await websocket.send(json.dumps({"type": "pong"}))
                            continue

                        elif data.get("type") == "chat_start":
                            # Chat started
                            continue

                        elif data.get("type") == "chat_chunk":
                            # Stream content
                            content = data.get("content", "")
                            if content:
                                print(content, end="", flush=True)
                                full_response += content

                        elif data.get("type") == "chat_end":
                            # Chat completed
                            break

                        elif data.get("type") == "error":
                            print(f"\n  │  Error: {data.get('message')}")
                            break

                    except asyncio.TimeoutError:
                        print("\n  │  Response timeout")
                        break
                    except json.JSONDecodeError:
                        # Non-JSON message, skip
                        continue

                total_time = round((time.time() - start_time) * 1000, 2)
                ttfb = round((first_chunk_time - start_time) * 1000, 2) if first_chunk_time else 0

                print("\n  │")
                print(f"  │  Time to first byte: {ttfb}ms")
                print(f"  │  Total time: {total_time}ms")
                print(f"  │  Response length: {len(full_response)} chars")
                print("  └─")

                if i < len(messages):
                    await asyncio.sleep(1)

            print_section("Test Complete")
            print("\n  All messages sent successfully")
            print("  WebSocket connection maintained throughout")
            print_separator()

    except websockets.exceptions.WebSocketException as e:
        print(f"\n  WebSocket error: {e}")
    except Exception as e:
        print(f"\n  Unexpected error: {e}")


if __name__ == "__main__":
    try:
        asyncio.run(test_websocket_chat())
    except KeyboardInterrupt:
        print("\n\n  Test interrupted by user")
        sys.exit(0)
