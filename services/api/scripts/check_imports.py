#!/usr/bin/env python3
"""
Modular Monolith Boundary Checker.
Scans files in app/modules/ to ensure no illegal direct imports between modules'
internal implementation files (e.g. models, repo). Modules must communicate
via service interface or events.
"""

import ast
import sys
from importlib.util import resolve_name
from pathlib import Path

MODULES_DIR = Path(__file__).resolve().parent.parent / "app" / "modules"


def check_module_boundaries() -> int:
    if not MODULES_DIR.exists():
        print("No modules directory found.")
        return 0

    violations = []
    # ponytail: static imports only; add runtime isolation before executing untrusted agents.
    app_dir = MODULES_DIR.parent
    for namespace in ("ai", "agents", "engines"):
        for py_file in (app_dir / namespace).glob("**/*.py"):
            try:
                tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            except (SyntaxError, OSError) as exc:
                violations.append(f"Failed to parse {py_file}: {type(exc).__name__}")
                continue
            package = ".".join(("app", *py_file.relative_to(app_dir).parts[:-1]))
            for node in ast.walk(tree):
                imports = []
                if isinstance(node, ast.Import):
                    imports = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    if node.level:
                        try:
                            module = resolve_name("." * node.level + module, package)
                        except ImportError:
                            violations.append(f"Invalid relative import in {py_file}")
                            continue
                    imports = [module, *(f"{module}.{alias.name}" for alias in node.names)]
                for imported in imports:
                    parts = imported.split(".")
                    if (
                        imported == "app.core.db"
                        or imported.startswith("app.core.db.")
                        or parts[0] in {"psycopg", "psycopg2", "asyncpg", "sqlalchemy", "sqlite3"}
                        or (
                            imported.startswith("app.modules.")
                            and any(p in {"repo", "repository", "models"} for p in parts[3:])
                        )
                    ):
                        violations.append(f"AI persistence import in {py_file}: {imported}")
    module_names = [
        d.name for d in MODULES_DIR.iterdir() if d.is_dir() and not d.name.startswith("_")
    ]

    for mod in module_names:
        mod_path = MODULES_DIR / mod
        for py_file in mod_path.glob("**/*.py"):
            try:
                tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            except Exception as e:
                violations.append(f"Failed to parse {py_file}: {e}")
                continue

            for node in ast.walk(tree):
                imports = []
                if isinstance(node, ast.Import):
                    imports = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    if node.level:
                        package = ".".join(("app", *py_file.relative_to(app_dir).parts[:-1]))
                        try:
                            module = resolve_name("." * node.level + module, package)
                        except ImportError:
                            violations.append(f"Invalid relative import in {py_file}")
                            continue
                    imports = [module, *(f"{module}.{alias.name}" for alias in node.names)]
                for imported in imports:
                    for other_mod in module_names:
                        if other_mod != mod:
                            banned_models = f"app.modules.{other_mod}.models"
                            banned_repo = f"app.modules.{other_mod}.repo"
                            if imported.startswith(banned_models) or imported.startswith(
                                banned_repo
                            ):
                                violations.append(
                                    f"Illegal direct internal import in {py_file}: {imported}"
                                )

    if violations:
        print("ERROR: Modular monolith import violations detected:")
        for v in violations:
            print(f"  - {v}")
        return 1

    print("SUCCESS: Modular boundary check passed (0 violations).")
    return 0


if __name__ == "__main__":
    sys.exit(check_module_boundaries())
