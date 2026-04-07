import httpx
import asyncio
import time
import sys


BACKEND_URL = "http://localhost:8000"
GATEWAY_URL = "http://localhost:8080"


def print_separator():
    print("\n" + "=" * 70)


def print_section(title):
    print("\n" + "─" * 70)
    print(f"  {title}")
    print("─" * 70)


async def test_chat():
    """Complete test: Client → Backend (auth) → Gateway → OpenClaw (chat)"""

    print_separator()
    print("   CLAIRIFY CHAT POC - Client Test")
    print("   Architecture: Client → Gateway (Tailscale) → OpenClaw")
    print_separator()

    # AUTHENTICATION (Client → Backend)
    print_section("PHASE 1: Authentication")
    print("\n  Client → Backend (http://localhost:8000)")

    start_time = time.time()

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{BACKEND_URL}/auth/chat",
                json={"user_id": "alice", "password": "pass1"}
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

    auth_data = response.json()
    auth_time = round((time.time() - start_time) * 1000, 2)

    print(f"\n  Authenticated as: {auth_data['user_id']}")
    print(f"  Auth time: {auth_time}ms")
    print(f"  Session token: {auth_data['session_token'][:20]}...")
    print(f"  Gateway URL: {auth_data['gateway_url']}")
    print(f"\n  {auth_data['message']}")

    session_token = auth_data['session_token']
    gateway_url = auth_data.get("gateway_url") or GATEWAY_URL

    # CHAT (Client → Gateway → OpenClaw)
    print_section("PHASE 2: Direct Chat (Backend NOT Involved)")
    print("\n  Flow: Client → Gateway → (Tailscale) → OpenClaw")
    print("        Backend has zero involvement from here")

    # Test messages
    messages = [
        "Hello! This is a test message.",
        "Can you tell me what you are in one short sentence?",
        "Thank you! Goodbye."
    ]

    for i, msg in enumerate(messages, 1):
        print(f"\n  ┌─ Message {i}/{len(messages)}")
        print("  │")
        print(f"  │  You: {msg}")

        start_time = time.time()

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    f"{gateway_url}/api/chat",
                    json={
                        "model": "tinyllama:latest",
                        "messages": [{"role": "user", "content": msg}],
                        "stream": False
                    },
                    headers={"Authorization": f"Bearer {session_token}"}
                )
        except httpx.ConnectError:
            print("  │")
            print("  │  Cannot connect to gateway")
            print("  └─")
            continue
        except httpx.TimeoutException:
            print("  │")
            print("  │  Request timed out (OpenClaw may be slow)")
            print("  └─")
            continue
        except Exception as e:
            print("  │")
            print(f" │  Error: {e}")
            print("  └─")
            continue

        latency = round((time.time() - start_time) * 1000, 2)

        if response.status_code == 200:
            reply_data = response.json()

            # Extract reply text
            choices = reply_data.get("choices", [])
            if choices:
                reply_text = choices[0].get("message", {}).get("content", "")

                # Truncate if too long
                if len(reply_text) > 150:
                    display_text = reply_text[:150] + "..."
                else:
                    display_text = reply_text

                print("  │")
                print(f"  │  OpenClaw: {display_text}")
            else:
                print("  │")
                print(f"  │  Response: {reply_data}")

            print("  │")
            print(f" │  Latency: {latency}ms")
            print("  │  Success - message went: Client → Gateway → OpenClaw")
        else:
            print("  │")
            print(f"  │  Error {response.status_code}: {response.text[:100]}")

        print("  └─")

        # Small delay between messages
        if i < len(messages):
            await asyncio.sleep(1)


if __name__ == "__main__":
    try:
        asyncio.run(test_chat())
    except KeyboardInterrupt:
        print("\n\n  Test interrupted by user")
        sys.exit(0)
