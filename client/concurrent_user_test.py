import argparse
import asyncio
import json
import statistics
import time
from dataclasses import dataclass

import httpx
import websockets


BACKEND_URL = "http://localhost:8000"
GATEWAY_WS_URL = "ws://localhost:8080/ws/chat"
DEFAULT_MODEL = "tinyllama:latest"
TEST_USERS = [
    {"user_id": "alice", "password": "pass1"},
    {"user_id": "bob", "password": "pass2"},
]


@dataclass
class RequestResult:
    ok: bool
    latency_ms: float
    ttfb_ms: float = 0  # Time to first byte
    status_code: int | None = None
    error: str | None = None


async def authenticate(
    backend_url: str, credentials: dict[str, str]
) -> tuple[str, str]:
    """Authenticate with backend and get token"""
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(f"{backend_url}/auth/chat", json=credentials)
        response.raise_for_status()
        payload = response.json()
        return payload["session_token"], payload["user_id"]


async def send_websocket_chat(
    ws_url: str,
    session_token: str,
    user_id: str,
    model: str,
    message: str,
) -> RequestResult:
    """Send chat message via WebSocket"""
    start = time.perf_counter()
    first_chunk_time = None

    try:
        async with websockets.connect(ws_url) as websocket:
            # Authenticate
            await websocket.send(json.dumps({
                "token": session_token,
                "user_id": user_id
            }))

            auth_response = await websocket.recv()
            auth_data = json.loads(auth_response)

            if auth_data.get("type") == "error":
                return RequestResult(
                    ok=False,
                    latency_ms=(time.perf_counter() - start) * 1000,
                    error=f"auth_failed: {auth_data.get('message')}"
                )

            # Send chat request
            await websocket.send(json.dumps({
                "type": "chat",
                "model": model,
                "messages": [{"role": "user", "content": message}]
            }))

            # Receive response
            full_response = ""

            while True:
                chunk = await asyncio.wait_for(websocket.recv(), timeout=60)

                if first_chunk_time is None:
                    first_chunk_time = time.perf_counter()

                data = json.loads(chunk)

                if data.get("type") == "chat_chunk":
                    content = data.get("content", "")
                    full_response += content

                elif data.get("type") == "chat_end":
                    break

                elif data.get("type") == "error":
                    return RequestResult(
                        ok=False,
                        latency_ms=(time.perf_counter() - start) * 1000,
                        error=data.get("message")
                    )

            latency_ms = (time.perf_counter() - start) * 1000
            ttfb_ms = (first_chunk_time - start) * 1000 if first_chunk_time else 0

            return RequestResult(
                ok=True,
                latency_ms=latency_ms,
                ttfb_ms=ttfb_ms,
                status_code=200
            )

    except asyncio.TimeoutError:
        return RequestResult(
            ok=False,
            latency_ms=(time.perf_counter() - start) * 1000,
            error="timeout"
        )
    except websockets.exceptions.WebSocketException as exc:
        return RequestResult(
            ok=False,
            latency_ms=(time.perf_counter() - start) * 1000,
            error=f"websocket_error: {exc}"
        )
    except Exception as exc:
        return RequestResult(
            ok=False,
            latency_ms=(time.perf_counter() - start) * 1000,
            error=str(exc)
        )


async def run_virtual_user(
    user_index: int,
    args: argparse.Namespace,
    semaphore: asyncio.Semaphore,
    results: list[RequestResult],
) -> None:
    """Run a virtual user test"""
    credentials = TEST_USERS[user_index % len(TEST_USERS)]

    async with semaphore:
        try:
            session_token, user_id = await authenticate(args.backend_url, credentials)
        except Exception as exc:
            results.append(
                RequestResult(
                    ok=False,
                    latency_ms=0,
                    error=f"auth_failed: {exc}",
                )
            )
            return

        for message_index in range(args.messages):
            message = (
                f"Load test user {user_index + 1}, "
                f"message {message_index + 1} of {args.messages}."
            )

            result = await send_websocket_chat(
                args.ws_url,
                session_token,
                user_id,
                args.model,
                message
            )
            results.append(result)


def print_summary(results: list[RequestResult], total_time_s: float) -> None:
    """Print test summary"""
    successes = [item for item in results if item.ok]
    failures = [item for item in results if not item.ok]
    latencies = [item.latency_ms for item in successes]
    ttfbs = [item.ttfb_ms for item in successes if item.ttfb_ms > 0]

    print("\n" + "=" * 70)
    print("WebSocket Concurrent Load Test Summary")
    print("=" * 70)
    print(f"Total requests: {len(results)}")
    print(f"Successful: {len(successes)}")
    print(f"Failed: {len(failures)}")
    print(f"Success rate: {len(successes) / len(results) * 100:.1f}%")
    print(f"Total runtime: {total_time_s:.2f}s")
    print(f"Requests/sec: {len(results) / total_time_s:.2f}")

    if latencies:
        print("\nLatency (total time):")
        print(f"  Average: {statistics.mean(latencies):.2f}ms")
        print(f"  Median: {statistics.median(latencies):.2f}ms")
        print(f"  Min: {min(latencies):.2f}ms")
        print(f"  Max: {max(latencies):.2f}ms")
        print(f"  P95: {sorted(latencies)[int(len(latencies) * 0.95)]:.2f}ms")

    if ttfbs:
        print("\nTime to First Byte:")
        print(f"  Average: {statistics.mean(ttfbs):.2f}ms")
        print(f"  Median: {statistics.median(ttfbs):.2f}ms")
        print(f"  Min: {min(ttfbs):.2f}ms")
        print(f"  Max: {max(ttfbs):.2f}ms")

    if failures:
        print("\nFailure samples:")
        for item in failures[:5]:
            detail = item.error or f"status={item.status_code}"
            print(f"  - {detail}")


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="WebSocket concurrent load test for Clairify chat."
    )
    parser.add_argument("--users", type=int, default=10, help="Number of virtual users")
    parser.add_argument("--messages", type=int, default=1, help="Messages per user")
    parser.add_argument("--concurrency", type=int, default=5, help="Max concurrent users")
    parser.add_argument("--backend-url", default=BACKEND_URL, help="Backend URL")
    parser.add_argument("--ws-url", default=GATEWAY_WS_URL, help="Gateway WebSocket URL")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Model to use")
    args = parser.parse_args()

    if args.users < 1 or args.messages < 1 or args.concurrency < 1:
        raise SystemExit("users, messages, and concurrency must all be >= 1")

    print("=" * 70)
    print("WebSocket Concurrent Load Test")
    print("=" * 70)
    print(f"Backend URL: {args.backend_url}")
    print(f"WebSocket URL: {args.ws_url}")
    print(f"Model: {args.model}")
    print(f"Virtual users: {args.users}")
    print(f"Messages per user: {args.messages}")
    print(f"Concurrency: {args.concurrency}")
    print(f"Total requests: {args.users * args.messages}")

    semaphore = asyncio.Semaphore(args.concurrency)
    results: list[RequestResult] = []

    start = time.perf_counter()
    await asyncio.gather(
        *(run_virtual_user(index, args, semaphore, results) for index in range(args.users))
    )
    total_time_s = time.perf_counter() - start

    print_summary(results, total_time_s)


if __name__ == "__main__":
    asyncio.run(main())

# Commands to test
# python concurrent_user_test.py --users 5 --messages 1 --concurrency 2
# python concurrent_user_test.py --users 20 --messages 2 --concurrency 5
# python concurrent_user_test.py --users 100 --messages 2 --concurrency 50
# python concurrent_user_test.py --users 10 --messages 3 --concurrency 3
# python concurrent_user_test.py --users 30 --messages 5 --concurrency 10
