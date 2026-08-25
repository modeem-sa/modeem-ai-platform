# Modeem AI Platform — Architecture Overview

> **Status note:** This document distinguishes clearly between what is **implemented today** (Foundation phase) and what is **planned**. Anything under "Direction" or "Future" is not built yet.

## Why the platform is separate from Odoo

Odoo is the system of record for business data. Modeem is deliberately a separate platform because:

- **Independent lifecycle:** automation logic evolves faster than ERP customizations and must be deployable without touching Odoo.
- **Blast-radius isolation:** a failing workflow or AI agent must never destabilize the ERP.
- **Multi-system future:** the platform will orchestrate more than Odoo (email, messaging, external APIs).
- **Upgrade safety:** avoiding custom Odoo modules keeps Odoo upgrades cheap.

## Future Odoo Bridge concept (not implemented)

A dedicated bridge service will be the only component that talks to Odoo. It will:

- Translate Odoo records/webhooks into platform events (using the shared event envelope).
- Apply per-tenant credentials and rate limits.
- Isolate Odoo API versions behind a stable internal contract.

## Event-driven architecture direction

All cross-module communication will happen through events using the shared envelope in `packages/event-contracts`:

- `event_id`, `event_name`, `event_version` — identity and evolution
- `tenant_id`, `company_id` — isolation boundaries
- `correlation_id`, `causation_id` — end-to-end traceability
- `idempotency_key` — safe retries

**Today:** only the Pydantic schema exists. No broker, no consumers. Redis is configured as a future transport candidate but has no worker implementation.

## Workflow Engine direction (not implemented)

A future engine will execute user-defined workflows (n8n-like) with: versioned workflow definitions, step-level execution records, retries with idempotency, and human-approval steps. The `Executions` and `Workflows` sections in the dashboard are placeholders for this.

## Security boundaries

- The web app never talks to the database; it only calls the API.
- The API is the single enforcement point for authentication, authorization, and tenant scoping (all **planned**, none implemented yet).
- Secrets live in environment variables; no secrets are committed to the repository.

## Tenant and company isolation

**Today:** the `Tenant` model and `tenant_id` columns (e.g. on `AuditLog`) prepare the data model for isolation. **This is structural preparation only — complete multi-tenancy security is NOT implemented.**

**Direction:** every query will be tenant-scoped at the service layer; events carry `tenant_id`/`company_id`; per-tenant credentials for external systems.

## Future AI governance principles

- AI agents act only through the same audited, tenant-scoped APIs as humans.
- Every AI action produces an `AuditLog` entry with `actor_type = "ai_agent"` and a correlation id.
- Human approval gates for high-impact actions.
- No AI component holds direct database or Odoo credentials.
