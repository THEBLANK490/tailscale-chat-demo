import httpx
import asyncio
import json
import time

BACKEND_URL = "http://localhost:8000"
OPENCLAW_ADMIN_EMAIL = "admin@localhost"
OPENCLAW_ADMIN_PASSWORD = "admin"


async def user_chat(user_id: str, password: str, messages: list[str]):
    """
    Simulate one user chatting with OpenClaw.
    Uses OpenAI-compatible REST API with SSE streaming.
    Connection goes directly via Tailscale — backend NOT involved.
    """

    print(f"\n{'─'*50}")
    print(f"{user_id}")
    print(f"{'─'*50}")

    # Auth via Backend
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            f"{BACKEND_URL}/auth/chat",
            json={"user_id": user_id, "password": password}
        )

    if r.status_code != 200:
        print(f"Auth failed: {r.json()}")
        return

    auth = r.json()
    openclaw_url = auth["openclaw_url"]
    print("Authenticated")
    print("OpenClaw: {openclaw_url}")
    print("Backend involved from here: NO\n")

    # Direct chat via Tailscale
    openclaw_headers = await get_openclaw_headers(openclaw_url)
    if not openclaw_headers:
        print("OpenClaw signin failed")
        return

    # First, find available models
    model = await find_model(openclaw_url, openclaw_headers)
    if not model:
        print("No model found. Will try anyway.")
        model = "default"

    for msg in messages:
        print(f"{user_id}: {msg}")
        sent_at = time.time()

        # Try streaming
        reply = await chat_streaming(openclaw_url, openclaw_headers, model, user_id, msg)

        if not reply:
            # Fallback: non-streaming
            reply = await chat_non_streaming(openclaw_url, openclaw_headers, model, user_id, msg)

        if reply:
            latency = round((time.time() - sent_at) * 1000, 2)
            print(f"OpenClaw: {reply[:200]}")
            print(f"{latency}ms\n")
        else:
            print(" No response\n")

        await asyncio.sleep(0.5)

    print(f"{user_id} done")


async def get_openclaw_headers(openclaw_url: str) -> dict[str, str] | None:
    """Sign in to OpenClaw and return auth headers for later API calls."""

    signin_endpoints = [
        "/api/v1/auths/signin",
        "/api/auths/signin",
    ]
    payload = {
        "email": OPENCLAW_ADMIN_EMAIL,
        "password": OPENCLAW_ADMIN_PASSWORD,
    }

    async with httpx.AsyncClient(timeout=10) as client:
        for endpoint in signin_endpoints:
            try:
                r = await client.post(f"{openclaw_url}{endpoint}", json=payload)
                if r.status_code == 200:
                    data = r.json()
                    token = data.get("token")
                    if token:
                        print(f"OpenClaw session ready (via {endpoint})")
                        return {"Authorization": f"Bearer {token}"}
            except Exception:
                continue

    return None


async def find_model(openclaw_url: str, headers: dict[str, str]) -> str | None:
    """Find what models are available in OpenClaw"""

    model_endpoints = [
        "/ollama/api/tags",
        "/api/models",
        "/api/v1/models",
    ]

    async with httpx.AsyncClient(timeout=10) as client:
        for endpoint in model_endpoints:
            r = await client.get(f"{openclaw_url}{endpoint}", headers=headers)
            if r.status_code == 200:
                data = r.json()
                models = data["models"]
                if models:
                    model_name = models[0].get("name")
                    print(f"Model found: {model_name} (via {endpoint})")
                    return model_name

    return None


async def chat_streaming(
    openclaw_url: str, headers: dict[str, str], model: str, user_id: str, message: str
) -> str | None:
    """
    Chat using SSE streaming (Server-Sent Events).
    This gives real-time token-by-token response.
    Like WebSocket but over HTTP — this is how ChatGPT works.
    """

    chat_endpoints = [
        "/api/chat/completions",
        "/api/v1/chat/completions",
    ]

    payload = {
        "model": model,
        "messages": [
            {"role": "user", "content": message}
        ],
        "stream": True
    }

    for endpoint in chat_endpoints:
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                async with client.stream(
                    "POST",
                    f"{openclaw_url}{endpoint}",
                    json=payload,
                    headers={**headers, "Content-Type": "application/json"}
                ) as response:

                    if response.status_code != 200:
                        continue

                    full_reply = ""

                    async for line in response.aiter_lines():
                        if not line:
                            continue

                        if line.startswith("data: "):
                            data_str = line[6:]

                            if data_str.strip() == "[DONE]":
                                break

                            try:
                                data = json.loads(data_str)

                                choices = data.get("choices", [])
                                if choices:
                                    delta = choices[0].get("delta", {})
                                    content = delta.get("content", "")
                                    if content:
                                        full_reply += content
                                        # Print token by token
                                        print(content, end="", flush=True)

                            except json.JSONDecodeError:
                                continue

                    if full_reply:
                        print()
                        return full_reply

        except Exception as e:
            print("Error: ", e)

    return None


async def chat_non_streaming(
    openclaw_url: str, headers: dict[str, str], model: str, user_id: str, message: str
) -> str | None:
    """Fallback: non-streaming chat"""

    chat_endpoints = [
        ("/api/chat/completions", {
            "model": model,
            "messages": [{"role": "user", "content": message}],
            "stream": False
        }),
        ("/ollama/api/chat", {
            "model": model,
            "messages": [{"role": "user", "content": message}],
            "stream": False
        }),
        ("/ollama/api/generate", {
            "model": model,
            "prompt": message,
            "stream": False
        }),
    ]

    async with httpx.AsyncClient(timeout=60) as client:
        for endpoint, payload in chat_endpoints:
            try:
                r = await client.post(
                    f"{openclaw_url}{endpoint}",
                    json=payload,
                    headers=headers,
                )

                if r.status_code == 200:
                    data = r.json()

                    # OpenAI format
                    choices = data.get("choices", [])
                    if choices:
                        return choices[0].get("message", {}).get("content", "")

                    # Ollama format
                    if "message" in data:
                        return data["message"].get("content", "")
                    if "response" in data:
                        return data["response"]

            except Exception as e:
                print("Error: ", e)

    return None


async def test_concurrent(openclaw_url: str, model: str):
    """Prove multiple users can chat simultaneously"""

    print(f"\n{'='*50}")
    print("CONCURRENT TEST — Same OpenClaw, 3 Users")
    print(f"{'='*50}")

    async def quick_chat(uid: str, msg: str):
        sent = time.time()
        headers = await get_openclaw_headers(openclaw_url)
        if not headers:
            print(f"[{uid}] â† signin failed")
            return False
        reply = await chat_non_streaming(openclaw_url, headers, model, uid, msg)
        latency = round((time.time() - sent) * 1000, 2)
        print(f"[{uid}] → {msg}")
        print(f"[{uid}] ← {str(reply)[:100] if reply else 'no reply'}")
        print(f"[{uid}]  {latency}ms\n")
        return reply is not None

    start = time.time()
    results = await asyncio.gather(
        quick_chat("alice", "Say hello to Alice"),
        quick_chat("bob", "Say hello to Bob"),
        quick_chat("charlie", "Say hello to Charlie"),
    )
    total = round((time.time() - start) * 1000, 2)

    success = sum(results)
    print(f"Results: {success}/3 succeeded in {total}ms")


async def main():
    print("=" * 50)
    print("CLAIRIFY — Single OpenClaw, Multiple Users")
    print("=" * 50)

    # Check OpenClaw
    print("\n Checking OpenClaw via Tailscale...")
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            r = await client.get(f"{BACKEND_URL}/tailscale/status")
            status = r.json()
            if status.get("openclaw_reachable"):
                print(f"OpenClaw at {status['openclaw_ip']}")
                print(f"Latency: {status['latency_ms']}ms")
                openclaw_url = f"http://{status['openclaw_ip']}:8001"
            else:
                print("Not reachable")
                return
        except Exception as e:
            print(f"Backend not running: {e}")
            return

    # Find model
    print("\n Finding available models...")
    openclaw_headers = await get_openclaw_headers(openclaw_url)
    model = await find_model(openclaw_url, openclaw_headers) if openclaw_headers else None

    # Sequential test
    print(f"\n{'='*50}")
    print("SEQUENTIAL TEST (streaming)")
    print(f"{'='*50}")

    await user_chat("alice", "pass1", [
        "Hello! Say hi in one sentence.",
        "What is Tailscale in one sentence?",
    ])

    await user_chat("bob", "pass2", [
        "Hi! Tell me a short joke.",
    ])

    # Concurrent test
    if model:
        await test_concurrent(openclaw_url, model)

    # Sessions
    print(f"\n{'='*50}")
    print("ACTIVE SESSIONS")
    print(f"{'='*50}")

    async with httpx.AsyncClient() as client:
        r = await client.get(f"{BACKEND_URL}/sessions")
        sessions = r.json()
        print(f"Total: {sessions['total_active']}")
        for uid, info in sessions['sessions'].items():
            print(f"- {uid} → {info['openclaw_ip']}")
        print(f"{sessions['note']}")


if __name__ == "__main__":
    asyncio.run(main())
