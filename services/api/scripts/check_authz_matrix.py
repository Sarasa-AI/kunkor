#!/usr/bin/env python3
"""
Authz Matrix & Deny-by-default Checker.
Inspects FastAPI routes in app.main. Every route must either:
1. Be explicitly registered in the public bypass whitelist (e.g., /healthz), OR
2. Have explicit Action authorization dependency / attribute.
Fails with non-zero exit code if any unregistered route lacks authz.
"""

import sys

from app.main import app

PUBLIC_WHITELIST = {
    "/healthz",
    "/docs",
    "/docs/oauth2-redirect",
    "/openapi.json",
    "/redoc",
}


AUTHZ_DEPENDENCY_NAMES = {
    "require_auth",
    "require_permission",
    "require_student_access",
    "verify_auth",
    "check_authz",
    "AuthzGuard",
}


def is_authz_dependency(dep: object) -> bool:
    call = getattr(dep, "call", dep)
    if getattr(call, "__authz_enforcing__", False):
        return True
    name = getattr(call, "__name__", "") or getattr(call.__class__, "__name__", "")
    return name in AUTHZ_DEPENDENCY_NAMES


def has_valid_authz(route: object) -> bool:
    endpoint = getattr(route, "endpoint", None)
    has_marker = getattr(endpoint, "__authz_required__", False) or bool(
        getattr(endpoint, "__authz_policy__", None)
    )
    if has_marker:
        return True

    route_deps = getattr(route, "dependencies", []) or []
    if any(is_authz_dependency(d) for d in route_deps):
        return True

    dependant = getattr(route, "dependant", None)
    if dependant and hasattr(dependant, "dependencies"):
        if any(is_authz_dependency(d) for d in dependant.dependencies):
            return True

    return False


def check_authz() -> int:
    unauthorized_routes = []
    total_routes = 0

    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", set())
        if not path:
            continue
        total_routes += 1

        if path in PUBLIC_WHITELIST:
            continue

        if not has_valid_authz(route):
            unauthorized_routes.append((path, methods))

    print(f"Authz Matrix Check: Evaluated {total_routes} routes.")
    if unauthorized_routes:
        print("ERROR: Found routes without explicit authorization (Deny-by-default failure):")
        for p, m in unauthorized_routes:
            print(f"  - {list(m)} {p}")
        return 1

    print("SUCCESS: 100% of routes meet authorization criteria.")
    return 0


if __name__ == "__main__":
    sys.exit(check_authz())
