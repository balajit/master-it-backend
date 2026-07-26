import logging
import os
from typing import Any, Dict, List

import bcrypt
from fastapi import APIRouter, Depends, HTTPException

from auth import create_token, get_current_user
from database import (
    assign_role,
    create_local_user,
    create_permission,
    get_all_permissions,
    get_roles_with_permissions,
    get_user_by_email,
    get_user_roles_with_permissions,
    grant_permission,
    has_permission,
    list_users,
    revoke_permission,
    upsert_user,
)
from schemas import (
    AssignRole,
    CreatePermission,
    GrantPermission,
    LocalLogin,
    LocalRegister,
    RevokePermission,
    TokenPayload,
    UserProfile,
)

router: APIRouter = APIRouter(prefix="/api", tags=["users"])
logger: logging.Logger = logging.getLogger(__name__)


def require_permission(permission_name: str):
    """Dependency that checks the authenticated user has a specific permission."""

    async def _check(
        user: Dict[str, Any] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        if not await has_permission(user["id"], permission_name):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user

    return _check


@router.post("/auth/google")
async def auth_google(payload: TokenPayload) -> Dict[str, str]:
    from google.auth.transport import requests
    from google.oauth2 import id_token

    decoded: Dict[str, Any] = id_token.verify_oauth2_token(
        payload.id_token, requests.Request(), os.getenv("GOOGLE_CLIENT_ID")
    )

    user_id: int = await upsert_user(
        google_id=decoded["sub"],
        email=decoded["email"],
        name=decoded["name"],
        picture_url=decoded["picture"],
    )

    token: str
    _: str
    token, _ = await create_token(user_id)
    return {"access_token": token, "token_type": "bearer"}


@router.post("/auth/register")
async def register(payload: LocalRegister) -> Dict[str, str]:
    password_hash: str = bcrypt.hashpw(
        payload.password.encode(), bcrypt.gensalt()
    ).decode()
    user_id: int
    try:
        user_id = await create_local_user(
            email=payload.email,
            password_hash=password_hash,
            name=payload.name,
            phone=payload.phone,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    token: str
    _: str
    token, _ = await create_token(user_id)
    return {"access_token": token, "token_type": "bearer"}


@router.post("/auth/login")
async def login(payload: LocalLogin) -> Dict[str, str]:
    user: Dict[str, Any] | None = await get_user_by_email(payload.email)
    if not user or not user.get("password_hash"):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not bcrypt.checkpw(payload.password.encode(), user["password_hash"].encode()):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token: str
    _: str
    token, _ = await create_token(user["id"])
    return {"access_token": token, "token_type": "bearer"}


@router.get("/me", response_model=UserProfile)
async def get_me(user: Dict[str, Any] = Depends(get_current_user)) -> UserProfile:
    roles = await get_user_roles_with_permissions(user["id"])
    return UserProfile(
        id=user["id"],
        email=user["email"],
        name=user["name"],
        picture_url=user.get("picture_url") or "",
        phone=user.get("phone") or "",
        auth_provider=user["auth_provider"],
        roles=roles,
    )


@router.get("/roles")
async def get_roles(
    user: Dict[str, Any] = Depends(require_permission("permission:create")),
) -> Any:
    return await get_roles_with_permissions()


@router.get("/permissions", status_code=200)
async def get_permissions(
    user: Dict[str, Any] = Depends(require_permission("permission:create")),
) -> List[Dict[str, Any]]:
    return await get_all_permissions()


@router.post("/roles/permissions", status_code=201)
async def add_permission(
    payload: GrantPermission,
    user: Dict[str, Any] = Depends(require_permission("permission:create")),
) -> Dict[str, Any]:
    granted: List[str] = []
    for perm_name in payload.permission_names:
        try:
            await grant_permission(payload.role_name, perm_name)
            granted.append(perm_name)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    logger.info(
        "Permissions %s granted to role '%s' by user %s",
        granted,
        payload.role_name,
        user["id"],
    )
    return {
        "message": f"Permissions granted to role '{payload.role_name}'",
        "permissions": granted,
    }


@router.post("/permissions", status_code=201)
async def create_permission_endpoint(
    payload: CreatePermission,
    user: Dict[str, Any] = Depends(require_permission("permission:create")),
) -> Dict[str, Any]:
    try:
        perm_id: int = await create_permission(payload.name)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    logger.info("Permission '%s' created by user %s", payload.name, user["id"])
    return {"id": perm_id, "name": payload.name}


@router.delete("/roles/permissions", status_code=204)
async def revoke_permission_endpoint(
    payload: RevokePermission,
    user: Dict[str, Any] = Depends(require_permission("permission:create")),
) -> None:
    await revoke_permission(payload.role_name, payload.permission_name)
    logger.info(
        "Permission '%s' revoked from role '%s' by user %s",
        payload.permission_name,
        payload.role_name,
        user["id"],
    )


@router.get("/users", status_code=200)
async def list_users_endpoint(
    user: Dict[str, Any] = Depends(require_permission("permission:create")),
) -> List[Dict[str, Any]]:
    return await list_users()


@router.put("/users/{user_id}/roles", status_code=200)
async def assign_role_endpoint(
    user_id: int,
    payload: AssignRole,
    user: Dict[str, Any] = Depends(require_permission("permission:create")),
) -> Dict[str, Any]:
    try:
        await assign_role(user_id, payload.role_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    logger.info(
        "Role '%s' assigned to user %s by user %s",
        payload.role_name,
        user_id,
        user["id"],
    )
    return {"message": f"Role '{payload.role_name}' assigned to user {user_id}"}
