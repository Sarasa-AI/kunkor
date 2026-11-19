#!/usr/bin/env python3
"""
Authz Matrix & Deny-by-default Checker.
Inspects FastAPI routes in app.main. Every route must either:
1. Be explicitly registered in the public bypass whitelist (e.g., /healthz), OR
2. Have an explicit authorization dependency.
Fails with non-zero exit code if any unregistered route lacks authz.
"""

import sys

from app.core.authz import has_valid_authz, is_public_route, iter_routes
from app.main import app


def check_authz() -> int:
    unauthorized_routes = []
    total_routes = 0

    for route in iter_routes(app.routes):
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", set())
        if not path:
            continue
        total_routes += 1

        if is_public_route(route):
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
