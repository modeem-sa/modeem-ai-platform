import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models import Tenant


def test_tenant_crud_in_memory() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        tenant = Tenant(name="Acme", code="acme")
        session.add(tenant)
        session.commit()

        loaded = session.query(Tenant).filter_by(code="acme").one()
        assert isinstance(loaded.id, uuid.UUID)
        assert loaded.name == "Acme"
        assert loaded.is_active is True
        assert loaded.created_at is not None
        assert loaded.updated_at is not None
