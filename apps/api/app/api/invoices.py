"""Authenticated, CSRF-protected PDF invoice review and Odoo draft export."""
import hashlib
import json
import re
import uuid
from datetime import UTC, date, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, model_validator
from pypdf import PdfReader
from sqlalchemy.orm import Session

from app.api.csrf import require_csrf
from app.api.deps import get_current_user, get_db, require_odoo_resource_scope, require_service_scope
from app.integrations.odoo.errors import ConnectorError
from app.integrations.odoo.invoice_writer import create_draft_invoice
from app.models import Connection, InvoiceDocument, Tenant, TenantMembership, User
from app.services.connection_auth import resolve_auth_material
from app.services.credential_crypto import decrypt_credentials
from app.core.config import get_settings
from app.services.audit import record_audit

router = APIRouter(prefix="/api/v1/invoices", tags=["invoices"])
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._ -]{0,240}\.pdf$", re.I)
_MAX = 8 * 1024 * 1024

class Line(BaseModel):
    description: str = Field(min_length=1, max_length=500)
    quantity: float = Field(gt=0, le=1_000_000)
    unit_price: float = Field(ge=0, le=1_000_000_000)
    tax_ids: list[int] = Field(default_factory=list, max_length=20)
    @model_validator(mode="after")
    def ids(self):
        if any(isinstance(x, bool) or x < 1 for x in self.tax_ids): raise ValueError("tax_ids must be positive")
        return self

class Review(BaseModel):
    invoice_type: str = Field(pattern="^(customer|vendor)$")
    partner_id: int = Field(gt=0)
    invoice_date: date
    due_date: date | None = None
    currency_id: int | None = Field(default=None, gt=0)
    reference: str | None = Field(default=None, max_length=255)
    notes: str | None = Field(default=None, max_length=5000)
    lines: list[Line] = Field(min_length=1, max_length=100)
class UpdateRequest(Review):
    expected_version: int = Field(ge=1)
    @model_validator(mode="after")
    def due_after_invoice(self):
        if self.due_date is not None and self.due_date < self.invoice_date:
            raise ValueError("due_date must not be before invoice_date")
        return self

class VersionRequest(BaseModel):
    expected_version: int = Field(ge=1)
class SubmitRequest(VersionRequest): pass
class RejectRequest(VersionRequest):
    note: str = Field(min_length=1, max_length=2000)
class ApproveRequest(VersionRequest):
    expected_hash: str = Field(min_length=64, max_length=64)

def _role(db: Session, user: User, tenant_id: uuid.UUID) -> str | None:
    if user.is_superuser:
        return "superuser" if db.get(Tenant, tenant_id) else None
    row = db.query(TenantMembership).filter_by(tenant_id=tenant_id, user_id=user.id, is_active=True).one_or_none()
    return row.role if row else None
def _require_financial_scope(db: Session, user: User, tenant_id: uuid.UUID) -> None:
    if _role(db, user, tenant_id) == "customer":
        raise HTTPException(
            status_code=403,
            detail="Customer accounts use the service-request portal",
        )
    require_service_scope(db, user, tenant_id, "financial")
    require_odoo_resource_scope(db, user, tenant_id, "accounting_entries")
def _doc(db: Session, user: User, invoice_id: uuid.UUID, lock=False) -> InvoiceDocument:
    q = db.query(InvoiceDocument).filter_by(id=invoice_id)
    if lock: q = q.with_for_update()
    result = q.one_or_none()
    if result is None or _role(db,user,result.tenant_id) is None: raise HTTPException(404, "Invoice not found")
    _require_financial_scope(db, user, result.tenant_id)
    return result
def _out(x: InvoiceDocument) -> dict:
    return {"id":str(x.id),"tenant_id":str(x.tenant_id),"filename":x.filename,"sha256":x.sha256,"status":x.status,
      "version":x.version,"manual_review_required":not bool(x.extracted_text),"extracted_text":x.extracted_text,
      "invoice_type":x.invoice_type,"partner_id":x.partner_id,"invoice_date":x.invoice_date,"due_date":x.due_date,
      "currency_id":x.currency_id,"reference":x.reference,"notes":x.notes,"lines":json.loads(x.lines_json) if x.lines_json else [],
      "reviewed_hash":_digest(x) if x.lines_json else None,"approved_hash":x.approved_hash,"odoo_move_id":x.odoo_move_id,"odoo_attachment_id":x.odoo_attachment_id,
      "rejection_note":x.rejection_note,"created_at":x.created_at,"updated_at":x.updated_at}
def _path(x: InvoiceDocument) -> Path:
    root = Path(get_settings().invoice_upload_dir).resolve()
    candidate = (root / x.storage_key).resolve()
    if root not in candidate.parents: raise HTTPException(500, "Invalid invoice storage path")
    return candidate
def _digest(x: InvoiceDocument) -> str:
    source = {"invoice_type":x.invoice_type,"partner_id":x.partner_id,"invoice_date":str(x.invoice_date),"due_date":str(x.due_date) if x.due_date else None,
      "currency_id":x.currency_id,"reference":x.reference,"notes":x.notes,"lines":json.loads(x.lines_json or "[]"),"sha256":x.sha256}
    return hashlib.sha256(json.dumps(source,sort_keys=True,separators=(",",":")).encode()).hexdigest()

@router.get("")
def list_invoices(tenant_id: uuid.UUID, user: User=Depends(get_current_user), db: Session=Depends(get_db)):
    if _role(db,user,tenant_id) is None: raise HTTPException(404, "Tenant not found")
    _require_financial_scope(db, user, tenant_id)
    return {"items":[{k:v for k,v in _out(x).items() if k != "extracted_text"} for x in db.query(InvoiceDocument).filter_by(tenant_id=tenant_id).order_by(InvoiceDocument.created_at.desc()).all()]}

@router.get("/{invoice_id}")
def get_invoice(invoice_id: uuid.UUID, user: User=Depends(get_current_user), db: Session=Depends(get_db)): return _out(_doc(db,user,invoice_id))

@router.post("/upload", dependencies=[Depends(require_csrf)])
async def upload_invoice(tenant_id: uuid.UUID=Form(...), file: UploadFile=File(...), user: User=Depends(get_current_user), db: Session=Depends(get_db)):
    if _role(db,user,tenant_id) is None: raise HTTPException(404, "Tenant not found")
    _require_financial_scope(db, user, tenant_id)
    if not file.filename or not _NAME.fullmatch(file.filename) or file.content_type != "application/pdf": raise HTTPException(422, "Only safely named PDF files are accepted")
    raw = await file.read(_MAX + 1)
    if len(raw) > _MAX or not raw.startswith(b"%PDF-"): raise HTTPException(422, "PDF is invalid or exceeds 8 MiB")
    try:
        reader = PdfReader(__import__("io").BytesIO(raw))
        if len(reader.pages) > 100:
            raise ValueError("PDF has too many pages")
        text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()[:100000]
    except Exception as exc: raise HTTPException(422, "PDF cannot be read") from exc
    ident = uuid.uuid4()
    item = InvoiceDocument(id=ident,tenant_id=tenant_id,uploaded_by_user_id=user.id,filename=file.filename,storage_key=f"{tenant_id}/{ident}.pdf",
      content_type="application/pdf",file_size=len(raw),sha256=hashlib.sha256(raw).hexdigest(),extracted_text=text or None,
      status="draft" if text else "manual_review",idempotency_marker=f"invoice-{ident.hex}")
    target = _path(item); target.parent.mkdir(mode=0o700, parents=True, exist_ok=True); target.write_bytes(raw); target.chmod(0o600)
    try:
        db.add(item)
        record_audit(db, action="invoice.uploaded", actor_type="user", actor_id=str(user.id), tenant_id=tenant_id, resource_type="invoice_document", resource_id=str(item.id), metadata={"sha256": item.sha256})
        db.commit()
    except Exception:
        db.rollback(); target.unlink(missing_ok=True); raise
    return _out(item)

@router.put("/{invoice_id}", dependencies=[Depends(require_csrf)])
def update_invoice(invoice_id: uuid.UUID, body: UpdateRequest, user: User=Depends(get_current_user), db: Session=Depends(get_db)):
    item=_doc(db,user,invoice_id,True)
    if item.version != body.expected_version or item.status not in ("draft","manual_review","rejected"): raise HTTPException(409, "Invoice has changed or cannot be edited")
    data=body.model_dump(); item.invoice_type=data["invoice_type"]; item.partner_id=data["partner_id"]; item.invoice_date=data["invoice_date"]; item.due_date=data["due_date"]; item.currency_id=data["currency_id"]; item.reference=data["reference"]; item.notes=data["notes"]; item.lines_json=json.dumps(data["lines"],sort_keys=True,separators=(",",":")); item.status="draft"; item.rejection_note=None; item.version+=1
    record_audit(db, action="invoice.updated", actor_type="user", actor_id=str(user.id), tenant_id=item.tenant_id, resource_type="invoice_document", resource_id=str(item.id), metadata={"version": item.version})
    db.commit(); return _out(item)

@router.post("/{invoice_id}/submit", dependencies=[Depends(require_csrf)])
def submit(invoice_id: uuid.UUID, body: SubmitRequest, user: User=Depends(get_current_user), db: Session=Depends(get_db)):
    item=_doc(db,user,invoice_id,True)
    if item.version!=body.expected_version or item.status!="draft" or not item.lines_json: raise HTTPException(409, "Invoice has changed or is incomplete")
    item.status="submitted"; item.version+=1
    record_audit(db, action="invoice.submitted", actor_type="user", actor_id=str(user.id), tenant_id=item.tenant_id, resource_type="invoice_document", resource_id=str(item.id), metadata={"version": item.version})
    db.commit(); return _out(item)

@router.post("/{invoice_id}/reject", dependencies=[Depends(require_csrf)])
def reject(invoice_id: uuid.UUID, body: RejectRequest, user: User=Depends(get_current_user), db: Session=Depends(get_db)):
    item=_doc(db,user,invoice_id,True)
    if item.version!=body.expected_version or item.status!="submitted": raise HTTPException(409, "Invoice has changed")
    item.status="rejected"; item.rejection_note=body.note; item.version+=1
    record_audit(db, action="invoice.rejected", actor_type="user", actor_id=str(user.id), tenant_id=item.tenant_id, resource_type="invoice_document", resource_id=str(item.id), metadata={"version": item.version})
    db.commit(); return _out(item)

@router.post("/{invoice_id}/approve", dependencies=[Depends(require_csrf)])
def approve(invoice_id: uuid.UUID, body: ApproveRequest, user: User=Depends(get_current_user), db: Session=Depends(get_db)):
    item=_doc(db,user,invoice_id,True); role=_role(db,user,item.tenant_id)
    if role not in ("superuser","owner","admin","manager"): raise HTTPException(403, "Insufficient role")
    require_odoo_resource_scope(db, user, item.tenant_id, "accounting_entries")
    digest=_digest(item)
    if item.version!=body.expected_version or item.status!="submitted" or body.expected_hash!=digest: raise HTTPException(409, "Invoice version or reviewed data has changed")
    connections=db.query(Connection).filter_by(tenant_id=item.tenant_id,provider="odoo",is_active=True,last_test_status="success").filter(Connection.selected_transport.in_(("xmlrpc","json2"))).all()
    if len(connections) != 1 or not connections[0].odoo_company_id: raise HTTPException(409, "Tenant must have exactly one active tested Odoo connection")
    conn=connections[0]
    if not conn.encrypted_credentials or conn.encryption_version is None: raise HTTPException(409, "Stored Odoo credentials are unavailable")
    try:
        creds=decrypt_credentials(conn.encrypted_credentials,tenant_id=conn.tenant_id,connection_id=conn.id,encryption_version=conn.encryption_version); auth=resolve_auth_material(conn.username,creds)
        receipt=create_draft_invoice(base_url=conn.base_url,database=conn.database_name,transport=conn.selected_transport,login=auth.login,secret=auth.secret,environment=get_settings().environment,company_id=conn.odoo_company_id,invoice_type=item.invoice_type or "",partner_id=item.partner_id or 0,invoice_date=item.invoice_date.isoformat(),due_date=item.due_date.isoformat() if item.due_date else None,currency_id=item.currency_id,reference=item.reference,notes=item.notes,lines=json.loads(item.lines_json),pdf_bytes=_path(item).read_bytes(),filename=item.filename,idempotency_marker=item.idempotency_marker)
    except (ConnectorError, ValueError, OSError) as exc:
        record_audit(db, action="invoice.approval_failed", actor_type="user", actor_id=str(user.id), tenant_id=item.tenant_id, resource_type="invoice_document", resource_id=str(item.id), metadata={"outcome":"odoo_failed"})
        db.commit()
        raise HTTPException(502, "Odoo draft invoice creation failed") from exc
    item.status="approved"; item.approved_hash=digest; item.approved_by_user_id=user.id; item.approved_at=datetime.now(UTC); item.connection_id=conn.id; item.odoo_move_id=int(receipt["move_id"]); item.odoo_attachment_id=int(receipt["attachment_id"]); item.verified_at=datetime.now(UTC); item.version+=1
    record_audit(db, action="invoice.approved", actor_type="user", actor_id=str(user.id), tenant_id=item.tenant_id, resource_type="invoice_document", resource_id=str(item.id), metadata={"move_id": item.odoo_move_id})
    db.commit(); return _out(item)

@router.get("/{invoice_id}/download")
def download(invoice_id: uuid.UUID, user: User=Depends(get_current_user), db: Session=Depends(get_db)):
    item=_doc(db,user,invoice_id); path=_path(item)
    if not path.is_file(): raise HTTPException(404, "Invoice file not found")
    return FileResponse(path,media_type="application/pdf",filename=item.filename)