## Ethitrust Backend

Component-based FastAPI backend for escrow, wallets, payments, KYC, disputes, notifications, and admin operations.

This repository is organized as multiple independently deployable services behind an API gateway, with:

- **HTTP APIs** via FastAPI
- **Synchronous inter-service calls** via gRPC
- **Asynchronous messaging/background work** via RabbitMQ + Celery
- **Per-service persistence** using PostgreSQL databases

---

## Architecture at a Glance

- `gateway/` — reverse proxy and single ingress for clients
- `components/*` — domain services (auth, user, wallet, escrow, etc.)
- `proto/` — shared gRPC contracts
- `scripts/` — helper scripts for protobuf generation and DB setup
- `docker-compose.yml` — local multi-service orchestration

High-level runtime flow:

1. Client calls the **Gateway**.
2. Gateway routes by URL prefix to the appropriate service.
3. Services communicate via **gRPC** for validation and critical synchronous workflows.
4. Events/tasks are handled asynchronously through **RabbitMQ/Celery**.

---

## Repository Structure

```text
ethitrust-backend/
├─ gateway/
├─ components/
│  ├─ auth/
│  ├─ user/
│  ├─ wallet/
│  ├─ escrow/
│  ├─ escrow_onetime/
│  ├─ escrow_milestone/
│  ├─ escrow_recurring/
│  ├─ payment_provider/
│  ├─ payment_link/
│  ├─ invoice/
│  ├─ payout/
│  ├─ bank/
│  ├─ kyc/
│  ├─ dispute/
│  ├─ organization/
│  ├─ webhook/
│  ├─ notification/
│  ├─ fee/
│  ├─ audit/
│  ├─ admin/
│  └─ workers/
├─ proto/
├─ scripts/
├─ components.md
├─ docker-compose.yml
└─ pyproject.toml
```

---

## Core Technologies

- Python 3.12+
- FastAPI + Uvicorn
- SQLAlchemy (async) + asyncpg
- gRPC (`grpcio`, `grpcio-tools`)
- RabbitMQ (`aio-pika`)
- Redis
- Celery (workers)
- Docker Compose

---

## Services and Primary Route Prefixes

The gateway maps incoming prefixes to internal services. Common prefixes include:

- `/auth` → Auth service
- `/users` → User service
- `/wallet` → Wallet service
- `/escrow` → Escrow service
- `/invoice` → Invoice service
- `/payment-link` → Payment Link service
- `/payout` → Payout service
- `/kyc` → KYC service
- `/dispute` → Dispute service
- `/notifications` → Notification service
- `/audit` → Audit service
- `/fee` → Fee service
- `/admin` → Admin service
- `/banks` → Bank service
- `/org` → Organization service
- `/providers` → Payment Provider service
- `/webhooks` → Webhook service

Each service also exposes a `GET /health` endpoint.

---

## Key API Surface (Selected)

### Auth

- `POST /auth/signup`
- `POST /auth/login`
- `POST /auth/verify-email`
- `POST /auth/resend-otp`
- `POST /auth/forgot-password`
- `POST /auth/reset-password`
- `GET /auth/me`

### User

- `GET /users/me`
- `PATCH /users/me`
- `GET /users/{user_id}`

### Wallet

- `GET /wallet`
- `POST /wallet`
- `GET /wallet/{wallet_id}`
- `GET /wallet/{wallet_id}/balance`
- `POST /wallet/{wallet_id}/fund`
- `GET /wallet/{wallet_id}/transactions`

### Escrow

- `POST /escrow`
- `GET /escrow`
- `GET /escrow/{escrow_id}`
- `POST /escrow/{escrow_id}/cancel`
- `POST /escrow/{escrow_id}/complete`
- Milestone endpoints under `/escrow/{escrow_id}/milestones/...`

### Other Domains

- Invoice: `/invoice...`
- Payment Link: `/payment-link...`
- Payout: `/payout...`
- KYC: `/kyc...`
- Dispute: `/escrow/{escrow_id}/dispute...`
- Organization: `/organizations...`
- Notification: `/notifications...`
- Admin: `/admin...`
- Webhook: `/webhook...`
- Fee: `/fee...`
- Audit: `/audit...`

---

## gRPC Contracts

Shared protobuf definitions live in `proto/`:

- `auth.proto`
- `user.proto`
- `wallet.proto`
- `escrow.proto`
- `payment_provider.proto`
- `notification.proto`

To generate Python stubs into component apps, use `scripts/generate_protos.sh`.

Recommended (cross-platform):

```bash
python scripts/generate_protos.py
```

Optional shortcut:

```bash
make protos
```

CI enforces proto/stub consistency with a drift-check workflow.
See `PROTO_WORKFLOW.md` for full details (development + production guidance).

---

## Local Development

### Prerequisites

- Docker + Docker Compose
- Python 3.12+ (for local non-container development)

### Environment Variables

This repo depends on environment variables (e.g., `SECRET_KEY`, DB URLs, KYC keys, broker URLs).

A root `.env` template has been added with placeholders:

- `.env`

Update it before running in non-trivial environments.

### Run with Docker Compose

From the repository root, run:

```bash
# Build all images
docker compose build

# Start the full stack in background
docker compose up -d

# Follow logs for all services
docker compose logs -f
```

Access:

- Gateway: `http://localhost:8000`
- Gateway health: `http://localhost:8000/health`

Useful operations:

```bash
# Rebuild and restart after changes
docker compose up -d --build

# Restart a single service
docker compose restart gateway

# Stop everything
docker compose down

# Stop and remove volumes (fresh DB state)
docker compose down -v
```

### Run a Single Service Locally (without Docker)

Example (gateway):

```bash
cd gateway
pip install -e .
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Example (component service):

```bash
cd components/auth
pip install -e .
uvicorn app.main:app --reload --host 0.0.0.0 --port 8001
```

> Most component services require dependent infrastructure (Postgres/RabbitMQ/Redis) and other services for gRPC calls.

### Run Workers

```bash
cd components/workers
pip install -e .
celery -A app.celery_app worker -B --loglevel=info
```

---

## Testing

Each component has its own tests under:

- `components/<service>/tests/unit`
- `components/<service>/tests/integration`

Many components also define test dependencies in their local `pyproject.toml`.

---

## Important Notes

- `escrow-service` build path is configured as `./components/escrow`.
- Gateway and payment-link service are aligned on `/payment-link`.

---

## Additional Documentation

- `components.md` — deep component-by-component design breakdown and dependency map.
- `PROTO_WORKFLOW.md` — protobuf generation workflow and CI drift enforcement.
- `PROTO_COMMUNICATION.md` — what protobuf does, current gRPC communication map, and ASCII architecture diagrams.

---

## Version


Current top-level project version: `0.1.0`.
