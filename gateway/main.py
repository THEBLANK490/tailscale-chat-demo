from typing import Optional

import httpx
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from config import config

app = FastAPI(title="Clairify Gateway")

OPENCLAW_TOKEN: Optional[str] = None


class ChatRequest(BaseModel):
    model: str = "llama3.2"
    messages: list[dict]
    stream: bool = False


async def get_openclaw_session(force_refresh: bool = False) -> Optional[str]:
    global OPENCLAW_TOKEN

    if OPENCLAW_TOKEN and not force_refresh:
        return OPENCLAW_TOKEN

    if not config.OPENCLAW_IP:
        print("OPENCLAW_IP not set in environment")
        return None

    openclaw_url = f"http://{config.OPENCLAW_IP}:{config.OPENCLAW_PORT}"
    print(f"Authenticating gateway with OpenClaw at {openclaw_url}")

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{openclaw_url}/api/v1/auths/signin",
                json={
                    "email": config.OPENCLAW_EMAIL,
                    "password": config.OPENCLAW_PASSWORD,
                },
            )
    except httpx.ConnectError as exc:
        print(f"Cannot connect to OpenClaw for signin: {exc}")
        return None
    except httpx.TimeoutException:
        print("OpenClaw signin request timed out")
        return None
    except Exception as exc:
        print(f"Unexpected OpenClaw signin error: {exc}")
        return None

    if response.status_code != 200:
        print(f"OpenClaw signin failed: {response.status_code} {response.text[:200]}")
        OPENCLAW_TOKEN = None
        return None

    OPENCLAW_TOKEN = response.json().get("token")
    if OPENCLAW_TOKEN:
        print("Gateway authenticated with OpenClaw")
    else:
        print("OpenClaw signin succeeded but no token was returned")
    return OPENCLAW_TOKEN


async def send_chat_to_openclaw(
    request: ChatRequest, token: Optional[str]
) -> httpx.Response:
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    async with httpx.AsyncClient(timeout=config.OPENCLAW_TIMEOUT) as client:
        return await client.post(
            f"http://{config.OPENCLAW_IP}:{config.OPENCLAW_PORT}/api/chat/completions",
            json=request.dict(),
            headers=headers,
        )


async def get_default_model(token: Optional[str]) -> Optional[str]:
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"http://{config.OPENCLAW_IP}:{config.OPENCLAW_PORT}/api/models",
                headers=headers,
            )
    except Exception as exc:
        print(f"Unable to fetch OpenClaw models: {exc}")
        return None

    if response.status_code != 200:
        print(f"OpenClaw models request failed: {response.status_code} {response.text[:200]}")
        return None

    data = response.json().get("data", [])
    if not data:
        print("OpenClaw returned no models")
        return None

    model_id = data[0].get("id")
    if model_id:
        print(f"Falling back to available OpenClaw model: {model_id}")
    return model_id


@app.on_event("startup")
async def startup():
    print("=" * 60)
    print("Gateway starting on Windows (using Windows Tailscale)")
    print(f"OpenClaw IP: {config.OPENCLAW_IP}")
    print("Backend URL: http://localhost:8000")
    print(f"OpenClaw auth email: {config.OPENCLAW_EMAIL}")
    print("=" * 60)


@app.post("/api/chat")
async def chat(request: ChatRequest, authorization: Optional[str] = Header(None)):
    global OPENCLAW_TOKEN

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing authorization token")

    if not config.OPENCLAW_IP:
        raise HTTPException(status_code=503, detail="OpenClaw IP not configured")

    print(f"Forwarding chat to OpenClaw via Tailscale ({config.OPENCLAW_IP})")

    try:
        response = await send_chat_to_openclaw(request, OPENCLAW_TOKEN)

        if response.status_code == 401:
            print("OpenClaw rejected the request as unauthenticated, refreshing session")
            OPENCLAW_TOKEN = await get_openclaw_session(force_refresh=True)

            if not OPENCLAW_TOKEN:
                raise HTTPException(
                    status_code=502,
                    detail="Gateway could not authenticate with OpenClaw",
                )

            response = await send_chat_to_openclaw(request, OPENCLAW_TOKEN)

        if response.status_code == 400 and "Model not found" in response.text:
            fallback_model = await get_default_model(OPENCLAW_TOKEN)
            if fallback_model and fallback_model != request.model:
                print(f"Retrying chat with fallback model '{fallback_model}'")
                request = request.model_copy(update={"model": fallback_model})
                response = await send_chat_to_openclaw(request, OPENCLAW_TOKEN)

        if response.status_code == 200:
            print("Got response from OpenClaw")
            return response.json()

        print(f"OpenClaw error: {response.status_code}")
        print(f"Response: {response.text[:200]}")
        raise HTTPException(status_code=response.status_code, detail=response.text)

    except HTTPException:
        raise
    except httpx.TimeoutException:
        print("OpenClaw request timed out")
        raise HTTPException(status_code=504, detail="Request timeout")
    except httpx.ConnectError as exc:
        print(f"Cannot connect to OpenClaw: {exc}")
        raise HTTPException(status_code=503, detail=f"Cannot connect: {exc}")
    except Exception as exc:
        print(f"Unexpected gateway error: {exc}")
        raise HTTPException(status_code=503, detail=str(exc))


@app.get("/health")
async def health():
    openclaw_reachable = False

    if config.OPENCLAW_IP:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(
                    f"http://{config.OPENCLAW_IP}:{config.OPENCLAW_PORT}/"
                )
                openclaw_reachable = response.status_code == 200
        except Exception:
            pass

    return {
        "service": "Gateway",
        "status": "healthy",
        "openclaw_ip": config.OPENCLAW_IP,
        "openclaw_reachable": openclaw_reachable,
        "openclaw_authenticated": OPENCLAW_TOKEN is not None,
        "running_on": "Windows (native Tailscale)",
    }


@app.get("/")
async def root():
    return {
        "service": "Clairify Gateway",
        "version": "1.0.0",
        "openclaw_ip": config.OPENCLAW_IP,
        "endpoints": {
            "chat": "POST /api/chat",
            "health": "GET /health",
        },
    }
