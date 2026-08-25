"""Ensure shared monorepo packages are importable.

The `packages/` directory holds shared contracts (e.g. event-contracts).
Until packages are published or installed in editable mode, we add the
directory to `sys.path` explicitly. Documented as a known limitation.
"""

import sys
from pathlib import Path

_PACKAGES_DIR = Path(__file__).resolve().parents[4] / "packages" / "event-contracts"


def ensure_shared_packages_importable() -> None:
    path = str(_PACKAGES_DIR)
    if path not in sys.path:
        sys.path.insert(0, path)
