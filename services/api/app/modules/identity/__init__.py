"""Identity module for student authentication, authorization, and profile."""

from app.modules.identity.repository import IdentityRepository
from app.modules.identity.router import router as identity_router
from app.modules.identity.service import IdentityService

__all__ = [
    "IdentityRepository",
    "IdentityService",
    "identity_router",
]
