import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Tuple

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from database import create_session, get_session

JWT_SECRET: str = os.environ["JWT_SECRET"]
ALGORITHM: str = "HS256"
TOKEN_EXPIRY_HOURS: int = 168  # 7 days

bearer_scheme: HTTPBearer = HTTPBearer()


async def create_token(user_id: int) -> Tuple[str, str]:
    session_id: str = uuid.uuid4().hex
    await create_session(session_id, user_id, days=7)
    payload: Dict[str, Any] = {
        "sub": str(user_id),
        "sid": session_id,
        "exp": datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRY_HOURS),
        "iat": datetime.now(timezone.utc),
    }
    token: str = jwt.encode(payload, JWT_SECRET, algorithm=ALGORITHM)
    return token, session_id


def decode_token(token: str) -> Dict[str, Any]:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> Dict[str, Any]:
    payload: Dict[str, Any] = decode_token(credentials.credentials)
    session: Dict[str, Any] | None = await get_session(payload["sid"])
    if not session:
        raise HTTPException(status_code=401, detail="Session expired")
    return {
        "id": session["user_id"],
        "email": session["email"],
        "name": session["name"],
        "picture_url": session["picture_url"],
        "phone": session.get("phone", ""),
        "auth_provider": session["auth_provider"],
        "roles": session.get("roles", []),
        "permissions": session.get("permissions", []),
    }
