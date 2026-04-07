import os


class Config:
    OPENCLAW_HOSTNAME = os.getenv("OPENCLAW_HOSTNAME", "openclaw-production")
    OPENCLAW_PORT = int(os.getenv("OPENCLAW_PORT", "8001"))
    OPENCLAW_IP = os.getenv("OPENCLAW_IP")
    OPENCLAW_TIMEOUT = 60
    OPENCLAW_EMAIL = os.getenv("OPENCLAW_EMAIL", "admin@localhost")
    OPENCLAW_PASSWORD = os.getenv("OPENCLAW_PASSWORD", "admin")


config = Config()
