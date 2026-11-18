"""JSON Web Token (JWT) helper utilities for Tap hoa 360."""

from datetime import datetime, timezone
import time
import jwt
import config


def create_jwt(payload: dict, expires_in_seconds: int) -> str:
    """Create a signed JWT token with an expiration time."""
    now_ts = int(time.time())
    data = payload.copy()
    if 'sub' in data:
        data['sub'] = str(data['sub'])
    data.update({
        "iat": now_ts,
        "exp": now_ts + expires_in_seconds,
    })
    return jwt.encode(data, config.JWT_SECRET_KEY, algorithm=config.JWT_ALGORITHM)


def decode_jwt(token: str) -> dict | None:
    """Decode and verify a signed JWT token. Returns payload dict or None if invalid/expired."""
    if not token or not isinstance(token, str):
        return None
    try:
        payload = jwt.decode(
            token,
            config.JWT_SECRET_KEY,
            algorithms=[config.JWT_ALGORITHM],
            options={"require": ["exp", "iat"]}
        )
        return payload
    except (jwt.PyJWTError, ValueError):
        return None
