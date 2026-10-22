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

        # Check if route endpoint has authz requirement marker
        endpoint = getattr(route, "endpoint", None)
        has_authz = getattr(endpoint, "__authz_required__", False)
        dependencies = getattr(route, "dependencies", [])

        if not has_authz and not dependencies:
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
