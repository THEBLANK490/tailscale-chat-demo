import os


class Config:
    # OpenClaw connection
    OPENCLAW_HOSTNAME = os.getenv("OPENCLAW_HOSTNAME", "openclaw-production")
    OPENCLAW_PORT = int(os.getenv("OPENCLAW_PORT", "8001"))
    OPENCLAW_IP = os.getenv("OPENCLAW_IP")
    OPENCLAW_TIMEOUT = 60
    OPENCLAW_EMAIL = os.getenv("OPENCLAW_EMAIL", "admin@localhost")
    OPENCLAW_PASSWORD = os.getenv("OPENCLAW_PASSWORD", "admin")

    # Performance optimizations
    MAX_CONNECTIONS = int(os.getenv("MAX_CONNECTIONS", "50"))
    MAX_KEEPALIVE_CONNECTIONS = int(os.getenv("MAX_KEEPALIVE_CONNECTIONS", "20"))
    TOKEN_REFRESH_INTERVAL = int(os.getenv("TOKEN_REFRESH_INTERVAL", "3300"))  # 55 minutes

    # WebSocket
    WS_HEARTBEAT_INTERVAL = int(os.getenv("WS_HEARTBEAT_INTERVAL", "30"))  # seconds


config = Config()
