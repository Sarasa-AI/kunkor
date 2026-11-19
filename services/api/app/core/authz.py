"""Shared authorization coverage checks for application startup and CI."""

from collections.abc import AsyncIterator, Iterable, Iterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

PUBLIC_PATHS = {
    "/healthz", "/docs", "/docs/oauth2-redirect", "/openapi.json", "/redoc"
}


def iter_routes(routes: Iterable) -> Iterator:
    for route in routes:
        contexts = getattr(route, "effective_route_contexts", None)
        if contexts is not None:
            yield from contexts()
        else:
            yield route


def has_valid_authz(route: object) -> bool:
    dependant = getattr(route, "dependant", None)
    return any(
        getattr(dep.call, "__authz_enforcing__", False) is True
        for dep in getattr(dependant, "dependencies", ())
    )


def is_public_route(route: object) -> bool:
    methods = getattr(route, "methods", None)
    return bool(
        getattr(route, "path", None) in PUBLIC_PATHS
        and methods
        and methods <= {"GET", "HEAD"}
    )


@asynccontextmanager
async def authorization_lifespan(app: FastAPI) -> AsyncIterator[None]:
    for route in iter_routes(app.routes):
        if not is_public_route(route) and not has_valid_authz(route):
            raise RuntimeError("API route has no explicit authorization policy")
    yield
