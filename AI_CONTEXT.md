# Modeem AI Platform - AI Context

## Important Instruction For AI Agents

Before making any changes, read this file.

The project has existing Docker and dependency fixes that are required for deployment.

Do NOT revert, remove, or replace these changes unless explicitly requested.

---

# Existing Deployment Fixes

## 1. Backend Dependency Configuration

File:

apps/api/pyproject.toml

Changes already applied:

- Updated Python backend dependency configuration.
- The project requires Python >= 3.12.
- FastAPI, SQLAlchemy 2, Alembic and required backend packages are defined here.

Purpose:

Keep backend dependency management compatible with Docker builds and CI/CD.

Do not rewrite this file without checking current deployment requirements.

---

# 2. Frontend Package Lock Fix

File:

apps/web/package-lock.json

Changes already applied:

- package-lock.json was regenerated using Node.js 20 environment.
- The previous lock file was generated from Replit environment and caused npm installation failures.
- The current lock file is required for reproducible CI/CD builds.

Purpose:

Ensure GitHub Actions and Docker builds install the same dependencies.

Do NOT delete package-lock.json.

Do NOT replace it with a new lock file generated from another Node version.

---

# 3. Frontend Docker Build Configuration

File:

infrastructure/docker/web.Dockerfile

Current deployment approach:

```dockerfile
FROM node:20-alpine

WORKDIR /srv/apps/web

COPY apps/web/package.json apps/web/package-lock.json ./

RUN npm ci --no-audit --no-fund

COPY apps/web .

RUN npm run build

EXPOSE 3000

CMD ["npm", "run", "start"]
