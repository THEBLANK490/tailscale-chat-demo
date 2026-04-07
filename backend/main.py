from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import secrets
from datetime import datetime
from config import config

app = FastAPI(title="Clairify Backend")
active_sessions = {}


class AuthRequest(BaseModel):
    user_id: str
    password: str


@app.post("/auth/chat")
async def authenticate(request: AuthRequest):
    user = config.USERS_DB.get(request.user_id)
    if not user or user["password"] != request.password:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    session_token = secrets.token_urlsafe(32)
    active_sessions[request.user_id] = {
        "session_token": session_token,
        "user_name": user["name"],
        "created_at": datetime.now().isoformat()
    }

    print(f"User '{request.user_id}' authenticated")
    print("Backend DONE - user will connect to gateway")

    return {
        "status": "authenticated",
        "user_id": request.user_id,
        "session_token": session_token,
        "gateway_url": config.GATEWAY_URL,
        "message": "Connect to gateway for chat. Backend is done."
    }


@app.get("/health")
async def health():
    return {
        "service": "Backend",
        "status": "healthy",
        "active_sessions": len(active_sessions)
    }


@app.get("/")
async def root():
    return {
        "service": "Clairify Backend",
        "version": "1.0.0",
        "endpoints": {
            "auth": "POST /auth/chat",
            "health": "GET /health"
        }
    }
