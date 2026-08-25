# Modeem AI Platform

Business automation and AI workflows for Odoo, designed for non-technical Arabic and English business users — similar in concept to n8n.

## Current implementation scope (Foundation phase)

- Minimal FastAPI backend with `GET /api/v1/health` and `GET /api/v1/info`
- SQLAlchemy 2 models: `Tenant`, `AuditLog` (+ Alembic initial migration)
- Shared Pydantic v2 event envelope in `packages/event-contracts`
- Minimal Next.js dashboard shell with Arabic/English toggle and RTL layout, sidebar, header, dashboard cards (demonstration data), and placeholder pages
- Docker Compose configuration (for use outside Replit), tests, and linting

**Not implemented yet:** Odoo integration, AI agents, authentication/authorization, real multi-tenancy security, workflow engine, Redis workers.

## Technology stack

Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, PostgreSQL, Next.js, TypeScript, Tailwind CSS, Docker Compose (external), Pytest, Ruff, ESLint.

## Project structure

```text
modeem-ai-platform/
├── apps/
│   ├── api/          # FastAPI backend (app/, tests/, alembic/)
│   └── web/          # Next.js dashboard shell
├── packages/
│   └── event-contracts/   # Shared Pydantic event envelope
├── docs/architecture/     # Architecture documentation
├── infrastructure/docker/ # Dockerfiles
├── docker-compose.yml
└── .env.example
```

## Local development

### Backend

```bash
cd apps/api
pip install .[dev]           # or use the Replit-managed environment
export DATABASE_URL=postgresql://...
alembic upgrade head
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Frontend

```bash
cd apps/web
npm install
npm run dev   # http://localhost:3000
```

### On Replit

Both services run as workflows ("Modeem API" on port 8000, "Modeem Web" on port 3000) using the built-in PostgreSQL database. Docker is not used on Replit.

## Docker startup (outside Replit)

```bash
cp .env.example .env
docker compose up --build
# API:  http://localhost:8000/api/v1/health
# Web:  http://localhost:3000
```

## Testing & linting

```bash
cd apps/api && python -m pytest        # backend tests
cd apps/api && python -m ruff check .  # Python lint
cd apps/web && npm run lint            # frontend lint
cd apps/web && npm run build           # frontend build
```

## Known limitations

- No authentication or authorization
- Tenant structure exists, but complete multi-tenancy security is NOT implemented
- Dashboard shows demonstration data only; no API wiring yet
- Redis is configuration-only; no workers
- Shared `packages/event-contracts` is imported via `sys.path` (not yet an installable package)
- Docker Compose is for non-Replit environments only

## Planned next phase

- Connections module foundation (credentials model + encrypted storage design)
- Basic authentication and tenant-scoped API access
- Wire the dashboard to real API endpoints
