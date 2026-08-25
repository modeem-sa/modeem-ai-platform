"""Pydantic schemas for the Connections module.

Credentials are NEVER returned to the client — ConnectionRead deliberately
omits the encrypted_creds field.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel


class ConnectionCreate(BaseModel):
    name: str
    connector_type: str
    creds: dict  # plaintext on ingress; encrypted before persistence


class ConnectionRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    connector_type: str
    is_active: bool
    created_by: uuid.UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}
