# Deployment Rules

Before modifying this repository:

- Read AI_CONTEXT.md first.
- Do not revert Docker fixes.
- Do not remove package-lock.json.
- Do not replace npm ci with npm install.
- Do not delete Docker volumes.
- Database data must always be preserved.

Current deployment model:

Docker Compose deployment.

Services:

- api
- web
- postgres
- redis

Any CI/CD implementation must preserve:
- environment variables
- database volumes
- persistent storage
