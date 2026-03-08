# AGENTS.md — ethitrust-backend

A Python microservices platform built with FastAPI, gRPC, RabbitMQ, and PostgreSQL following a
Component-Based Software Architecture (CBSA). 21 independently deployable services live under
`components/`, each with its own database, Dockerfile, `pyproject.toml`, and test suite.

---

## Build / Run Commands

```bash
# Full stack (all services, databases, message broker)
docker compose up -d --build
docker compose logs -f
docker compose down

# Run a single service locally (example: auth)
cd components/auth
pip install -e ".[test]"
uvicorn app.main:app --reload --host 0.0.0.0 --port 8001

# Background workers (Celery)
cd components/workers
pip install -e .
celery -A app.celery_app worker -B --loglevel=info

# Regenerate gRPC stubs from .proto files
python scripts/generate_protos.py   # cross-platform
make protos                          # shortcut
make protos-check                    # verify no proto drift (used in CI)
```

---

## Test Commands

Tests live inside each component and use **pytest + pytest-asyncio** with `asyncio_mode = "auto"`.

```bash
# Install test dependencies (always do this first)
cd components/<service>
pip install -e ".[test]"

# Run all tests for a component
pytest tests/

# Run a single test file
pytest tests/unit/test_service.py

# Run a single test function
pytest tests/unit/test_service.py::test_signup_success

# Run tests matching a keyword
pytest -k "test_login"

# Verbose output
pytest tests/integration/test_routes.py -v
```

No global test runner — each component is tested independently from its own directory.

---

## Repository Layout

```
components/<service>/
├── app/
│   ├── main.py          # FastAPI app factory, lifespan, health endpoint
│   ├── api.py           # Thin route handlers only — no business logic
│   ├── service.py       # Business logic
│   ├── repository.py    # SQLAlchemy data access layer
│   ├── models.py        # Pydantic request/response schemas
│   ├── db.py            # Engine, session factory, ORM model definitions
│   ├── security.py      # JWT, password hashing, auth dependencies
│   ├── messaging.py     # RabbitMQ publisher and consumer
│   ├── redis_client.py  # Redis async helpers
│   ├── grpc_server.py   # gRPC servicer implementation
│   └── grpc_clients.py  # gRPC stub wrappers for calling other services
├── tests/
│   ├── conftest.py      # Fixtures: in-memory DB, HTTP client, mocks
│   ├── unit/            # Mock the repository; pure Python, no I/O
│   └── integration/     # Real in-memory SQLite, mocked gRPC + RabbitMQ
├── Dockerfile
└── pyproject.toml
proto/                   # Shared .proto definitions (source of truth)
gateway/                 # Thin reverse-proxy — no business logic
scripts/                 # Proto generation and DB tooling
```

---

## Architecture Rules

- **One database per component** — never share tables across services.
- **No business logic in `api.py`** — route handlers call service methods only.
- **gRPC for synchronous calls** (token validation, balance checks, quota enforcement).
- **RabbitMQ for async events** (notifications, audit logs, analytics, state-change broadcasts).
- **All I/O is async** — no synchronous DB or HTTP calls anywhere.
- **Environment variables for all config** — no secrets or hardcoded values in code.
- **Generated `*_pb2.py` / `*_pb2_grpc.py` files are committed** and verified in CI via
  `make protos-check`. Never edit them by hand.
- **All monetary values stored as `BIGINT`** (smallest denomination: kobo/cents) — never floats.

---

## Code Style

### Imports

Always include `from __future__ import annotations` at the top. Order: stdlib → third-party → local.

```python
from __future__ import annotations

import os
import uuid
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import User
from app.repository import UserRepository
```

### Naming Conventions

| Entity | Convention | Example |
|---|---|---|
| Files | `snake_case.py` | `grpc_server.py`, `redis_client.py` |
| Classes | `PascalCase` | `AuthService`, `WalletRepository` |
| Functions / methods | `snake_case` | `get_by_email`, `create_access_token` |
| Variables | `snake_case` | `user_id`, `password_hash` |
| Constants | `UPPER_SNAKE_CASE` | `SECRET_KEY`, `EXCHANGE_NAME` |
| Private helpers | leading underscore | `_generate_otp()`, `_cache_key()` |
| gRPC servicer methods | `PascalCase` (protobuf convention) | `ValidateToken`, `GetUserById` |
| Pydantic request models | `PascalCase` + `Request` suffix | `SignupRequest`, `LoginRequest` |
| Pydantic response models | `PascalCase` + `Response` or `Out` | `TokenResponse`, `UserOut` |
| SQLAlchemy ORM models | `PascalCase` singular | `User`, `Wallet`, `AuditLog` |

### Type Annotations

All function signatures must have full parameter and return type annotations. Use SQLAlchemy 2.0
`Mapped[T]` / `mapped_column()` style. Use Pydantic v2 with `model_config = {"from_attributes": True}`
for ORM integration.

```python
# SQLAlchemy 2.0 typed columns
id: Mapped[uuid.UUID] = mapped_column(pg.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
email: Mapped[str] = mapped_column(String(255), unique=True)
first_name: Mapped[str | None] = mapped_column(String(100))

# Fully annotated function
async def create_access_token(
    sub: str,
    role: str = "user",
    extra_claims: dict | None = None,
) -> str: ...

# Async generator dependency
async def get_db() -> AsyncGenerator[AsyncSession, None]: ...
```

Prefer `str | None` over `Optional[str]` in new code.

### Error Handling

- HTTP errors: `raise HTTPException(status_code=..., detail="...")` — always use `status` constants.
- gRPC errors: `await context.abort(grpc.StatusCode.X, "message")`.
- Chain exceptions when re-raising: `raise HTTPException(...) from exc`.
- Never leak user existence in auth flows (return silently when email not found in `forgot_password`).
- `messaging.publish()` is fire-and-forget — log failures, do not propagate to the request.

```python
# Standard service error pattern
async def login(self, data: LoginRequest) -> str:
    user = await self.repo.get_by_email(data.email)
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")

# Exception chaining
try:
    payload = decode_token(token)
except JWTError as exc:
    raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired token") from exc
```

### Dependency Injection

Use a factory function in `api.py` to wire the repository and service:

```python
def get_service(db: Annotated[AsyncSession, Depends(get_db)]) -> AuthService:
    return AuthService(UserRepository(db))
```

Use `Annotated[T, Depends(...)]` (not the older `= Depends(...)` default-argument style).

### Decorators

- `@asynccontextmanager` for `lifespan` in `main.py`.
- `@field_validator("field") @classmethod` (Pydantic v2) for custom field validation.
- `@app.exception_handler(HTTPException)` for global exception formatting in `main.py`.
- `@staticmethod` for pure utility methods inside service classes.
- `# noqa: N802` inline suppression only for gRPC servicer methods (PascalCase required by protobuf).

---

## Testing Patterns

**Always mock external calls** — never hit real gRPC, RabbitMQ, or Redis in tests.

```python
# conftest.py — in-memory DB + HTTP client
TEST_DB = "sqlite+aiosqlite:///:memory:"

@pytest.fixture
async def db():
    engine = create_async_engine(TEST_DB)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine) as session:
        yield session
    await engine.dispose()

@pytest.fixture
async def client(db):
    app.dependency_overrides[get_db] = lambda: db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()

# Always mock gRPC and RabbitMQ
@pytest.fixture(autouse=True)
def mock_grpc(monkeypatch):
    monkeypatch.setattr("app.grpc_clients.validate_token", AsyncMock(return_value="uid-123"))

@pytest.fixture(autouse=True)
def mock_rabbitmq(monkeypatch):
    monkeypatch.setattr("app.messaging.publish", AsyncMock())
```

- **Unit tests** (`tests/unit/`): mock the repository with `AsyncMock`; no DB, no HTTP.
- **Integration tests** (`tests/integration/`): real in-memory SQLite, mocked gRPC + RabbitMQ.
- Use `app.dependency_overrides` to swap `get_db` — never patch SQLAlchemy internals.

---

## Inter-Service Communication

| Situation | Use |
|---|---|
| Token validation before serving a request | gRPC |
| Balance / quota check before a write | gRPC |
| Cross-service data fetch that must be fresh | gRPC |
| Welcome email after registration | RabbitMQ |
| Audit log entry | RabbitMQ |
| Analytics / tracking event | RabbitMQ |
| Notify downstream of a state change | RabbitMQ |

RabbitMQ exchange: `ethitrust` (topic). Routing key pattern: `<domain>.<event>` (e.g. `user.registered`).
gRPC ports: each service exposes `50051` internally; mapped to unique host ports in `docker-compose.yml`.
