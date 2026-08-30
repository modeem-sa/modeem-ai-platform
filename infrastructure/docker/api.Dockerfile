FROM python:3.12-slim

WORKDIR /srv

COPY packages/event-contracts /srv/packages/event-contracts
COPY apps/api /srv/apps/api

WORKDIR /srv/apps/api
RUN pip install --no-cache-dir .

ENV PYTHONPATH=/srv/apps/api:/srv/packages/event-contracts

EXPOSE 8000

# Apply pending schema migrations before accepting traffic. Production runs a
# single API container, so this keeps the external deploy script independent
# from repository layout while ensuring new code never starts on an old schema.
CMD ["sh", "-c", "python -m alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
