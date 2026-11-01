#!/usr/bin/env python3
"""
Modular Monolith Boundary Checker.
Scans files in app/modules/ to ensure no illegal direct imports between modules'
internal implementation files (e.g. models, repo). Modules must communicate
via service interface or events.
"""

import ast
import sys
from pathlib import Path

MODULES_DIR = Path(__file__).resolve().parent.parent / "app" / "modules"


def check_module_boundaries() -> int:
    if not MODULES_DIR.exists():
        print("No modules directory found.")
        return 0

    violations = []
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
                if isinstance(node, ast.ImportFrom) and node.module:
                    for other_mod in module_names:
                        if other_mod != mod:
                            banned_models = f"app.modules.{other_mod}.models"
                            banned_repo = f"app.modules.{other_mod}.repo"
                            if node.module.startswith(banned_models) or node.module.startswith(
                                banned_repo
                            ):
                                violations.append(
                                    f"Illegal direct internal import in {py_file}: {node.module}"
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
