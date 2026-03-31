from fastapi import FastAPI, HTTPException
import httpx
import secrets
import subprocess
import json
import time
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("backend")

app = FastAPI(title="Clairify Backend")

USERS_DB = {
    "alice": {"password": "pass1", "name": "Alice"},
    "bob": {"password": "pass2", "name": "Bob"},
    "charlie": {"password": "pass3", "name": "Charlie"},
}

OPENCLAW_PORT = 8001
OPENCLAW_IP = None

# Track active sessions
active_sessions: dict[str, dict] = {}


def find_openclaw_ip():
    """Find OpenClaw's Tailscale IP"""
    global OPENCLAW_IP

    try:
        result = subprocess.run(
            ["tailscale", "status", "--json"],
            capture_output=True, text=True
        )
        data = json.loads(result.stdout)

        for peer_id, peer in data.get("Peer", {}).items():
            hostname = peer.get("HostName", "")
            online = peer.get("Online", False)
            if "openclaw" in hostname.lower() and online:
                ip = peer["TailscaleIPs"][0]
                OPENCLAW_IP = ip
                return ip
        return None
    except Exception as e:
        logger.error(f"Error: {e}")
        return None


@app.post("/auth/chat")
async def auth_and_connect(data: dict):
    """
    Authenticate user.
    Return OpenClaw's direct URL.
    Each user will open their OWN WebSocket session.
    Backend is DONE after this.
    """
    start = time.time()
    user_id = data.get("user_id")
    password = data.get("password")

    # Auth
    user = USERS_DB.get(user_id)
    if not user or user["password"] != password:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Find OpenClaw
    openclaw_ip = find_openclaw_ip()
    if not openclaw_ip:
        raise HTTPException(status_code=503, detail="OpenClaw not reachable")

    # Generate session token
    session_token = secrets.token_urlsafe(32)

    # Track session
    active_sessions[user_id] = {
        "token": session_token,
        "openclaw_ip": openclaw_ip,
        "connected_at": time.time()
    }

    setup_time = round((time.time() - start) * 1000, 2)

    logger.info(f"'{user_id}' authenticated ({setup_time}ms)")
    logger.info(f"OpenClaw at {openclaw_ip}:{OPENCLAW_PORT}")
    logger.info("Backend DONE — user will connect directly")
    logger.info(f"Active sessions: {len(active_sessions)}")

    return {
        "status": "channel_ready",
        "user_id": user_id,
        "openclaw_url": f"http://{openclaw_ip}:{OPENCLAW_PORT}",
        "openclaw_ws_url": f"ws://{openclaw_ip}:{OPENCLAW_PORT}",
        "session_token": session_token,
        "setup_time_ms": setup_time,
        "message": "Connect directly to OpenClaw. Backend is out."
    }


@app.get("/sessions")
async def list_sessions():
    """See all active user sessions"""
    return {
        "total_active": len(active_sessions),
        "sessions": {
            uid: {
                "openclaw_ip": s["openclaw_ip"],
                "connected_since": round(time.time() - s["connected_at"], 1)
            }
            for uid, s in active_sessions.items()
        },
        "note": "All sessions point to SAME OpenClaw instance, different WS connections"
    }


@app.get("/tailscale/status")
async def tailscale_status():
    openclaw_ip = find_openclaw_ip()
    if not openclaw_ip:
        return {"openclaw_reachable": False}

    try:
        start = time.time()
        async with httpx.AsyncClient(timeout=5) as client:
            await client.get(f"http://{openclaw_ip}:{OPENCLAW_PORT}/")
        latency = round((time.time() - start) * 1000, 2)
        return {
            "openclaw_reachable": True,
            "openclaw_ip": openclaw_ip,
            "latency_ms": latency
        }
    except Exception as e:
        return {"openclaw_reachable": False, "error": str(e)}


@app.get("/health")
async def health():
    return {"service": "Clairify Backend", "status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
