"""Authorization discovery must include nested lazy FastAPI routers."""

from fastapi import APIRouter, Depends, FastAPI

from scripts.check_authz_matrix import has_valid_authz, iter_routes


def require_auth():
    pass


def test_nested_routes_keep_effective_prefix_and_inherited_authorization():
    child = APIRouter()

    @child.get("/protected")
    def protected():
        return {}

    parent = APIRouter()
    parent.include_router(child, prefix="/child", dependencies=[Depends(require_auth)])
    app = FastAPI()
    app.include_router(parent, prefix="/api")
    routes = {route.path: route for route in iter_routes(app.routes)}
    assert "/api/child/protected" in routes
    assert has_valid_authz(routes["/api/child/protected"])


def test_nested_unprotected_route_is_detected():
    child = APIRouter()

    @child.get("/unsafe")
    def unsafe():
        return {}

    app = FastAPI()
    app.include_router(child, prefix="/api")
    routes = {route.path: route for route in iter_routes(app.routes)}
    assert not has_valid_authz(routes["/api/unsafe"])
