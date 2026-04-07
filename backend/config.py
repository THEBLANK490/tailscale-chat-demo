import os


class Config:
    USERS_DB = {
        "alice": {"password": "pass1", "name": "Alice"},
        "bob": {"password": "pass2", "name": "Bob"},
    }
    GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost:8080")


config = Config()
