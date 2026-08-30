# Modeem AI Platform - Replit Development Rules

## Critical Architecture

This project was originally developed using Replit, but Replit is NOT the production deployment environment.

Replit is used ONLY for application development and AI-assisted coding.

The real production architecture is:

Replit Development
→ GitHub
→ main branch
→ GitHub Actions Self-Hosted Runner
→ External Ubuntu Server
→ Docker Compose
→ Production

The production server is completely external and independent from Replit.

## Replit Agent Responsibility

Replit Agent may modify application code, including:

- API business logic
- Web application code
- UI/UX
- application features
- tests
- application-level dependencies when necessary

Replit Agent is NOT responsible for production deployment infrastructure.

## Protected Infrastructure

During normal application development, DO NOT modify, delete, regenerate, or overwrite:

- .github/workflows/**
- docker-compose.yml
- infrastructure/docker/**
- production deployment scripts
- production server configuration

If an application change appears to require an infrastructure change, explain the required change first and wait for explicit user approval.

## External Deployment

Production deployment is performed on an external Ubuntu server using:

docker compose build
docker compose up -d

The GitHub Actions workflow uses a self-hosted runner on that external server.

Do NOT replace this architecture with Replit Deployment.

## No Replit Production Dependencies

Production must have ZERO runtime dependency on Replit infrastructure.

Never introduce production references to:

- package-firewall.replit.local
- replit.local
- Replit internal package registries
- Replit internal networking
- Replit internal proxies
- Replit-only runtime services

The external Ubuntu server must be able to deploy using standard public internet services.

## npm / package-lock.json

A previous production failure occurred because apps/web/package-lock.json contained hundreds of references to:

http://package-firewall.replit.local/npm/

This broke npm installation on the external Ubuntu server.

Never commit Replit internal registry URLs into package-lock.json.

After modifying Web dependencies, ensure:

grep -c 'package-firewall.replit.local' apps/web/package-lock.json

returns:

0

## Web Docker Build

The production Web Docker build must use deterministic installation with:

npm ci

Do NOT automatically replace npm ci with npm install.

Do NOT overwrite infrastructure/docker/web.Dockerfile during normal application development.

## Python API Packaging

The following configuration in apps/api/pyproject.toml is an intentional production fix and MUST be preserved:

[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["app*"]

Without this configuration, Docker API builds fail because setuptools discovers both app and alembic as top-level packages.

Do NOT remove or overwrite this configuration.

## Environment Variables

Production has its own .env file on the external Ubuntu server.

Never:

- commit .env
- hard-code production secrets
- replace production configuration with Replit Secrets
- assume Replit Secrets exist in production

## Source of Truth

GitHub main is the production source of truth.

Replit is only a development environment.

Every committed change must remain compatible with deployment on a normal external Ubuntu server with Docker.

## Final Rule

Replit Agent should modify APPLICATION CODE only during normal development.

Do NOT automatically modify production deployment infrastructure.

Do NOT introduce Replit runtime dependencies.

Do NOT overwrite existing deployment fixes.

External Ubuntu + Docker production compatibility has priority over Replit preview behavior.
