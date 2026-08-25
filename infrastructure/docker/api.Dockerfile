FROM python:3.12-slim

WORKDIR /srv

COPY packages/event-contracts /srv/packages/event-contracts
COPY apps/api /srv/apps/api

WORKDIR /srv/apps/api
RUN pip install --no-cache-dir .

ENV PYTHONPATH=/srv/apps/api:/srv/packages/event-contracts

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
