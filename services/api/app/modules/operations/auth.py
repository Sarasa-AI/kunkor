"""Admin and Operations authentication dependencies."""

from typing import Optional

from fastapi import Header, HTTPException, status

from app.core.config import settings


def require_admin_auth(
    x_admin_api_key: Optional[str] = Header(None, alias="X-Admin-Api-Key"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
) -> bool:
    """
    Verify admin API credentials via X-Admin-Api-Key or Authorization Bearer header.
    Guards administrative operations against unauthorized access.
    """
    expected = settings.ADMIN_API_KEY
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Admin API key is not configured.",
        )

    # 1. Check custom X-Admin-Api-Key header
    if x_admin_api_key and x_admin_api_key == expected:
        return True

    # 2. Check Bearer token in standard Authorization header
    if authorization:
        parts = authorization.strip().split()
        if len(parts) == 2 and parts[0].lower() == "bearer" and parts[1] == expected:
            return True

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Unauthorized: invalid or missing administrative credentials.",
    )


# Mark dependency for authz matrix compliance
setattr(require_admin_auth, "__authz_enforcing__", True)
