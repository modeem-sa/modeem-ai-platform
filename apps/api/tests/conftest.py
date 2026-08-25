import sys
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[1]
PACKAGES_DIR = API_DIR.parents[1] / "packages" / "event-contracts"

for p in (str(API_DIR), str(PACKAGES_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

# Re-export shared fixtures so sibling modules can use them without
# import-based redefinition (F811) issues.
from tests.test_auth_security import _fresh_db, seed  # noqa: F401
from tests.test_connections import _encryption_key, roles_seed  # noqa: F401
