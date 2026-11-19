"""Authorization discovery must include nested lazy FastAPI routers."""

import pytest
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

from app.core.authz import authorization_lifespan, has_valid_authz, iter_routes


def require_auth(x_test_authorized: str = Header(default="")) -> None:
    if x_test_authorized != "allow":
        raise HTTPException(403)


setattr(require_auth, "__authz_enforcing__", True)


def test_nested_routes_keep_effective_prefix_and_inherited_authorization():
    child = APIRouter()

    @child.get("/protected")
    def protected():
        return {}

    parent = APIRouter()
    parent.include_router(child, prefix="/child", dependencies=[Depends(require_auth)])
    app = FastAPI(lifespan=authorization_lifespan)
    app.include_router(parent, prefix="/api")
    routes = {route.path: route for route in iter_routes(app.routes)}
    assert "/api/child/protected" in routes
    assert has_valid_authz(routes["/api/child/protected"])
    with TestClient(app) as client:
        assert client.get("/api/child/protected").status_code == 403
        assert client.get(
            "/api/child/protected", headers={"X-Test-Authorized": "allow"}
        ).status_code == 200


def test_nested_unprotected_route_is_detected():
    child = APIRouter()

    @child.get("/unsafe")
    def unsafe():
        return {}

    app = FastAPI(lifespan=authorization_lifespan)
    app.include_router(child, prefix="/api")
    routes = {route.path: route for route in iter_routes(app.routes)}
    assert not has_valid_authz(routes["/api/unsafe"])
    with pytest.raises(RuntimeError, match="no explicit authorization policy"), TestClient(app):
        pass
