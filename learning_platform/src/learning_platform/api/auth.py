"""JWT authentication — validates tokens issued by the main app.

Both the main app (``src/auth.py``) and this module use the same
``JWT_SECRET`` environment variable and ``HS256`` algorithm.  The host
creates tokens via ``src/auth.py:create_token``; the LP only validates
them.  Keep the two modules in sync: same algorithm, same claim names,
same error messages.
"""

from __future__ import annotations

from typing import Any

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from learning_platform.config import get_settings

ALGORITHM: str = "HS256"

bearer_scheme = HTTPBearer()


def decode_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT token.

    Raises ``HTTPException(401)`` on expiry or invalid signature.
    Raises ``HTTPException(500)`` if ``JWT_SECRET`` is not set.
    """
    jwt_secret = get_settings().jwt_secret.strip()
    if not jwt_secret:
        raise HTTPException(status_code=500, detail="JWT_SECRET not configured")
    try:
        return jwt.decode(token, jwt_secret, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError as err:
        raise HTTPException(status_code=401, detail="Token expired") from err
    except jwt.InvalidTokenError as err:
        raise HTTPException(status_code=401, detail="Invalid token") from err


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> dict[str, Any]:
    """FastAPI dependency — extract the current user from a Bearer token."""
    return decode_token(credentials.credentials)
