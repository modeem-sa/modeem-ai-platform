"""Fixed, draft-only Odoo invoice and PDF attachment writer."""
import base64
import re
from datetime import date
from typing import Any

import httpx
from . import http as safe_http
from . import json2, legacy_xmlrpc, security
from .errors import ConnectorError

_MARKER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{7,63}")
_FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._ -]{0,240}\.pdf$", re.I)

def _id(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ConnectorError("unsupported_response", "invalid record id")
    return value
def _relation(value: Any) -> int:
    if not isinstance(value, (list, tuple)) or len(value) != 2: raise ConnectorError("unsupported_response", "invalid relation")
    return _id(value[0])

def _result(response: httpx.Response) -> Any:
    if response.status_code in (301,302,303,307,308): raise ConnectorError("unsupported_response", "redirect")
    if response.status_code == 401: raise ConnectorError("authentication_failed")
    if response.status_code == 403: raise ConnectorError("access_denied")
    if response.status_code >= 500: raise ConnectorError("server_unreachable")
    if response.status_code != 200: raise ConnectorError("unsupported_response")
    try:
        raw = response.json()
    except ValueError as exc: raise ConnectorError("unsupported_response") from exc
    return raw.get("result") if isinstance(raw, dict) and "result" in raw else raw

def _search(client: httpx.Client, base_url: str, database: str | None, transport: str, login: str, secret: str,
            model: str, domain: list, fields: list[str]) -> Any:
    if transport == "json2":
        return json2.search_read(client, base_url, database, secret, model=model, domain=domain, fields=fields, offset=0, limit=2, order="id asc")
    return legacy_xmlrpc.search_read(client, base_url, database, login, secret, model=model, domain=domain, fields=fields, offset=0, limit=2, order="id asc")

def _create(client: httpx.Client, base_url: str, database: str | None, transport: str, login: str, secret: str,
            model: str, values: dict[str, Any]) -> int:
    if transport == "json2":
        raw = json2.create_one(client, base_url, database, secret, model=model, values=values)
        return _id(raw[0] if isinstance(raw, list) and len(raw) == 1 else raw)
    return _id(legacy_xmlrpc.create_one(client, base_url, database, login, secret, model=model, values=values))

def create_draft_invoice(*, base_url: str, database: str | None, transport: str, login: str, secret: str,
                         environment: str, company_id: int, invoice_type: str, partner_id: int, invoice_date: str,
                         due_date: str | None, currency_id: int | None, reference: str | None, notes: str | None,
                         lines: list[dict[str, Any]], pdf_bytes: bytes, filename: str, idempotency_marker: str) -> dict[str, int | bool]:
    """Create/reconcile exactly one draft move and one attachment; never posts."""
    if transport not in ("xmlrpc", "json2") or not _MARKER.fullmatch(idempotency_marker) or not _FILENAME.fullmatch(filename):
        raise ConnectorError("invalid_configuration", "invalid invoice writer configuration")
    _id(company_id); _id(partner_id)
    if invoice_type not in ("customer", "vendor") or not isinstance(pdf_bytes, bytes) or not (0 < len(pdf_bytes) <= 8 * 1024 * 1024) or not pdf_bytes.startswith(b"%PDF-"):
        raise ConnectorError("invalid_configuration", "invalid invoice document")
    try:
        parsed_invoice_date = date.fromisoformat(invoice_date)
        if parsed_invoice_date.isoformat() != invoice_date: raise ValueError
        if due_date and date.fromisoformat(due_date) < parsed_invoice_date: raise ValueError
    except ValueError as exc: raise ConnectorError("invalid_configuration", "invalid invoice dates") from exc
    if currency_id is not None: _id(currency_id)
    if not isinstance(lines, list) or not (1 <= len(lines) <= 100): raise ConnectorError("invalid_configuration", "invalid invoice lines")
    for line in lines:
        if not isinstance(line, dict) or not isinstance(line.get("description"), str) or not line["description"].strip() or len(line["description"]) > 500 or not isinstance(line.get("quantity"), (int,float)) or isinstance(line["quantity"],bool) or not 0 < line["quantity"] <= 1e6 or not isinstance(line.get("unit_price"), (int,float)) or isinstance(line["unit_price"],bool) or not 0 <= line["unit_price"] <= 1e9 or not isinstance(line.get("tax_ids"),list) or len(line["tax_ids"]) > 20:
            raise ConnectorError("invalid_configuration", "invalid invoice lines")
        for tax_id in line["tax_ids"]: _id(tax_id)
    marker = f"MODEEM-INVOICE:{idempotency_marker}"
    security.enforce_outbound_policy(base_url, environment=environment)
    with safe_http.build_client(environment) as client:
        found = _search(client, base_url, database, transport, login, secret, "account.move",
                        [["company_id","=",company_id],["ref","=",marker]], ["id","company_id","state","ref"])
        if not isinstance(found, list) or len(found) > 1: raise ConnectorError("unsupported_response", "move reconciliation not unique")
        if found:
            move = found[0]
            if not isinstance(move, dict) or _relation(move.get("company_id")) != company_id or move.get("state") != "draft" or move.get("ref") != marker:
                raise ConnectorError("unsupported_response", "move verification mismatch")
            move_id = _id(move.get("id"))
            created = False
        else:
            move_type = "out_invoice" if invoice_type == "customer" else "in_invoice"
            values: dict[str, Any] = {"move_type":move_type, "company_id":company_id, "partner_id":partner_id,
              "invoice_date":invoice_date, "ref":marker, "invoice_line_ids":[[0,0,{"name":x["description"],"quantity":x["quantity"],"price_unit":x["unit_price"],"tax_ids":[[6,0,x["tax_ids"]]]}] for x in lines]}
            if due_date: values["invoice_date_due"] = due_date
            if currency_id: values["currency_id"] = currency_id
            if notes: values["narration"] = notes
            move_id = _create(client, base_url, database, transport, login, secret, "account.move", values)
            created = True
            verify = _search(client, base_url, database, transport, login, secret, "account.move", [["id","=",move_id],["company_id","=",company_id],["ref","=",marker]], ["id","state","ref"])
            if not isinstance(verify, list) or len(verify) != 1 or verify[0].get("state") != "draft": raise ConnectorError("unsupported_response", "draft move not verified")
        attachments = _search(client, base_url, database, transport, login, secret, "ir.attachment",
            [["res_model","=","account.move"],["res_id","=",move_id],["name","=",f"{marker}.pdf"]], ["id","res_id","res_model","name"])
        if not isinstance(attachments, list) or len(attachments)>1: raise ConnectorError("unsupported_response", "attachment reconciliation not unique")
        attachment_id = _id(attachments[0]["id"]) if attachments else _create(client, base_url, database, transport, login, secret, "ir.attachment",
            {"name":f"{marker}.pdf","type":"binary","datas":base64.b64encode(pdf_bytes).decode(),"mimetype":"application/pdf","res_model":"account.move","res_id":move_id})
        attachment_name = f"{marker}.pdf"
        verified = _search(client, base_url, database, transport, login, secret, "ir.attachment", [["id","=",attachment_id],["res_id","=",move_id],["res_model","=","account.move"]], ["id","name","res_id","res_model"])
        if not isinstance(verified, list) or len(verified) != 1 or not isinstance(verified[0],dict) or verified[0].get("name") != attachment_name or verified[0].get("res_id") != move_id or verified[0].get("res_model") != "account.move": raise ConnectorError("unsupported_response", "attachment not verified")
        return {"move_id":move_id, "attachment_id":attachment_id, "created":created}