import argparse
import asyncio
import statistics
import time
from dataclasses import dataclass

import httpx


BACKEND_URL = "http://localhost:8000"
DEFAULT_MODEL = "tinyllama:latest"
TEST_USERS = [
    {"user_id": "alice", "password": "pass1"},
    {"user_id": "bob", "password": "pass2"},
]


@dataclass
class RequestResult:
    ok: bool
    latency_ms: float
    status_code: int | None = None
    error: str | None = None


async def authenticate(
    client: httpx.AsyncClient, backend_url: str, credentials: dict[str, str]
) -> tuple[str, str]:
    response = await client.post(f"{backend_url}/auth/chat", json=credentials)
    response.raise_for_status()
    payload = response.json()
    return payload["session_token"], payload["gateway_url"]


async def send_chat(
    client: httpx.AsyncClient,
    gateway_url: str,
    session_token: str,
    model: str,
    message: str,
) -> RequestResult:
    start = time.perf_counter()
    try:
        response = await client.post(
            f"{gateway_url}/api/chat",
            json={
                "model": model,
                "messages": [{"role": "user", "content": message}],
                "stream": False,
            },
            headers={"Authorization": f"Bearer {session_token}"},
        )
        latency_ms = (time.perf_counter() - start) * 1000

        if response.status_code == 200:
            return RequestResult(ok=True, latency_ms=latency_ms, status_code=200)

        return RequestResult(
            ok=False,
            latency_ms=latency_ms,
            status_code=response.status_code,
            error=response.text[:200],
        )
    except httpx.TimeoutException:
        return RequestResult(
            ok=False,
            latency_ms=(time.perf_counter() - start) * 1000,
            error="timeout",
        )
    except httpx.ConnectError:
        return RequestResult(
            ok=False,
            latency_ms=(time.perf_counter() - start) * 1000,
            error="connect_error",
        )
    except Exception as exc:
        return RequestResult(
            ok=False,
            latency_ms=(time.perf_counter() - start) * 1000,
            error=str(exc),
        )


async def run_virtual_user(
    user_index: int,
    args: argparse.Namespace,
    semaphore: asyncio.Semaphore,
    results: list[RequestResult],
) -> None:
    credentials = TEST_USERS[user_index % len(TEST_USERS)]

    async with semaphore:
        async with httpx.AsyncClient(timeout=args.timeout) as client:
            try:
                session_token, gateway_url = await authenticate(
                    client, args.backend_url, credentials
                )
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
                result = await send_chat(
                    client, gateway_url, session_token, args.model, message
                )
                results.append(result)


def print_summary(results: list[RequestResult], total_time_s: float) -> None:
    successes = [item for item in results if item.ok]
    failures = [item for item in results if not item.ok]
    latencies = [item.latency_ms for item in successes]

    print("\n" + "=" * 70)
    print("Concurrent Load Test Summary")
    print("=" * 70)
    print(f"Total requests: {len(results)}")
    print(f"Successful: {len(successes)}")
    print(f"Failed: {len(failures)}")
    print(f"Total runtime: {total_time_s:.2f}s")

    if latencies:
        print(f"Average latency: {statistics.mean(latencies):.2f}ms")
        print(f"Median latency: {statistics.median(latencies):.2f}ms")
        print(f"Min latency: {min(latencies):.2f}ms")
        print(f"Max latency: {max(latencies):.2f}ms")

    if failures:
        print("\nFailure samples:")
        for item in failures[:5]:
            detail = item.error or f"status={item.status_code}"
            print(f"- {detail}")


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Concurrent load test for the Clairify chat flow."
    )
    parser.add_argument("--users", type=int, default=10, help="Number of virtual users.")
    parser.add_argument(
        "--messages", type=int, default=1, help="Number of chat requests per user."
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=5,
        help="Maximum number of virtual users running at the same time.",
    )
    parser.add_argument(
        "--backend-url",
        default=BACKEND_URL,
        help="Backend base URL, default is http://localhost:8000",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help="Model to request from the gateway.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=60,
        help="Per-request timeout in seconds.",
    )
    args = parser.parse_args()

    if args.users < 1 or args.messages < 1 or args.concurrency < 1:
        raise SystemExit("users, messages, and concurrency must all be >= 1")

    print("=" * 70)
    print("Starting concurrent load test")
    print("=" * 70)
    print(f"Backend URL: {args.backend_url}")
    print(f"Model: {args.model}")
    print(f"Virtual users: {args.users}")
    print(f"Messages per user: {args.messages}")
    print(f"Concurrency: {args.concurrency}")

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
