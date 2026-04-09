import jwt
from fastapi import WebSocketException
from config import config


def verify_token(token: str):
    try:
        payload = jwt.decode(token, config.JWT_SIGNING_KEY, algorithms=[config.JWT_ALGORITHM])

        return {
            "user_id": payload["sub"],
            "exp": payload.get("exp"),
        }

    except jwt.ExpiredSignatureError:
        raise WebSocketException(code=1008, reason="Token expired")

    except jwt.InvalidTokenError:
        raise WebSocketException(code=1008, reason="Invalid token")
