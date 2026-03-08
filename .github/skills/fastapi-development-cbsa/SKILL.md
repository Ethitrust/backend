---
name: fastapi-development-cbsa
description: Build Component-Based Software Architecture (CBSA) FastAPI systems where each domain (auth, users, orders, etc.) is an independently deployable service with its own Dockerfile and pyproject.toml. Use this skill when the user wants microservices or component-based FastAPI APIs with gRPC for synchronous inter-service calls (validations, balance checks, critical flows) and RabbitMQ for async messaging (notifications, audit logs, analytics, event broadcasts). Includes API gateway, docker-compose, and per-component test suites.
---

# FastAPI — Component-Based Software Architecture

Each domain is an **independently deployable component** with its own app code, dependencies, container, and test suite. Services communicate via **gRPC** (synchronous) or **RabbitMQ** (asynchronous).

## Repository Layout

```
repo/
├── components/
│   ├── auth/
│   │   ├── app/
│   │   │   ├── main.py
│   │   │   ├── api.py
│   │   │   ├── models.py
│   │   │   ├── service.py
│   │   │   └── repository.py
│   │   ├── tests/
│   │   │   ├── conftest.py
│   │   │   ├── unit/
│   │   │   └── integration/
│   │   ├── proto/             # gRPC .proto files owned by this component
│   │   ├── pyproject.toml
│   │   └── Dockerfile
│   │
│   ├── users/
│   │   ├── app/  ...          # same structure
│   │   ├── tests/ ...
│   │   ├── proto/
│   │   ├── pyproject.toml
│   │   └── Dockerfile
│   │
│   └── <domain>/              # repeat per bounded context
│
├── gateway/
│   ├── main.py                # reverse-proxy / aggregation layer
│   ├── Dockerfile
│   └── pyproject.toml
│
├── proto/                     # shared .proto definitions (cross-component)
└── docker-compose.yml
```

## Component Anatomy

### app/main.py — FastAPI entry point

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.api import router
import asyncio, logging
from app.messaging import start_consumer  # RabbitMQ consumer

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(start_consumer())
    logger.info("auth service starting")
    yield
    task.cancel()
    logger.info("auth service stopped")

app = FastAPI(title="Auth Service", lifespan=lifespan)
app.include_router(router, prefix="/auth")

@app.get("/health")
async def health(): return {"status": "ok"}
```

### app/models.py — Pydantic schemas

```python
from pydantic import BaseModel, EmailStr, Field, field_validator
from datetime import datetime
from enum import Enum

class UserRole(str, Enum):
    ADMIN = "admin"
    USER  = "user"

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    first_name: str = Field(..., max_length=100)
    last_name:  str = Field(..., max_length=100)

    @field_validator("password")
    @classmethod
    def strong_password(cls, v: str) -> str:
        if not any(c.isupper() for c in v) or not any(c.isdigit() for c in v):
            raise ValueError("Password must contain uppercase and digit")
        return v

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

class UserOut(BaseModel):
    id: str
    email: str
    role: UserRole
    created_at: datetime
    model_config = {"from_attributes": True}
```

### app/repository.py — Data access only

```python
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db import User

class UserRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_email(self, email: str) -> User | None:
        r = await self.db.execute(select(User).where(User.email == email.lower()))
        return r.scalar_one_or_none()

    async def get_by_id(self, user_id: str) -> User | None:
        r = await self.db.execute(select(User).where(User.id == user_id))
        return r.scalar_one_or_none()

    async def save(self, user: User) -> User:
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user
```

### app/service.py — Business logic

```python
from app.repository import UserRepository
from app.models import RegisterRequest
from app.db import User
from app.security import hash_password, verify_password, create_token
from app.messaging import publish                   # RabbitMQ
from app.grpc_clients import balance_client         # gRPC
from fastapi import HTTPException

class AuthService:
    def __init__(self, repo: UserRepository):
        self.repo = repo

    async def register(self, data: RegisterRequest) -> User:
        if await self.repo.get_by_email(data.email):
            raise HTTPException(409, "Email already registered")

        # gRPC: synchronous validation before write
        await balance_client.check_registration_quota()

        user = User(
            email=data.email.lower(),
            password_hash=hash_password(data.password),
            first_name=data.first_name,
            last_name=data.last_name,
        )
        user = await self.repo.save(user)

        # RabbitMQ: fire-and-forget broadcast
        await publish("user.registered", {"user_id": str(user.id), "email": user.email})
        return user

    async def authenticate(self, email: str, password: str) -> str:
        user = await self.repo.get_by_email(email)
        if not user or not verify_password(password, user.password_hash):
            raise HTTPException(401, "Invalid credentials")
        await publish("user.login", {"user_id": str(user.id)})   # audit log
        return create_token(str(user.id))
```

### app/api.py — Thin route handlers

```python
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Annotated
from app.db import get_db
from app.models import RegisterRequest, UserOut, TokenResponse
from app.repository import UserRepository
from app.service import AuthService
from app.security import get_current_user_id

router = APIRouter()

def get_service(db: Annotated[AsyncSession, Depends(get_db)]) -> AuthService:
    return AuthService(UserRepository(db))

@router.post("/register", response_model=UserOut, status_code=201)
async def register(data: RegisterRequest, svc: Annotated[AuthService, Depends(get_service)]):
    return await svc.register(data)

@router.post("/login", response_model=TokenResponse)
async def login(email: str, password: str, svc: Annotated[AuthService, Depends(get_service)]):
    token = await svc.authenticate(email, password)
    return {"access_token": token}

@router.get("/me", response_model=UserOut)
async def me(user_id: Annotated[str, Depends(get_current_user_id)],
             svc: Annotated[AuthService, Depends(get_service)]):
    return await svc.repo.get_by_id(user_id)
```

---

## gRPC — Synchronous Inter-Service Calls

Use gRPC for flows that **must complete before** proceeding: immediate validations, balance checks, quota enforcement, critical cross-service reads.

### proto/auth.proto

```protobuf
syntax = "proto3";
package auth;

service AuthValidator {
  rpc ValidateToken (TokenRequest) returns (TokenResponse);
  rpc CheckRegistrationQuota (QuotaRequest) returns (QuotaResponse);
}

message TokenRequest  { string token = 1; }
message TokenResponse { bool valid = 1; string user_id = 2; }
message QuotaRequest  {}
message QuotaResponse { bool allowed = 1; string reason = 2; }
```

Generate stubs: `python -m grpc_tools.protoc -I proto --python_out=app/proto --grpc_python_out=app/proto proto/auth.proto`

### gRPC server inside a component

```python
# app/grpc_server.py
import grpc
from concurrent import futures
from app.proto import auth_pb2, auth_pb2_grpc
from app.security import decode_token

class AuthValidatorServicer(auth_pb2_grpc.AuthValidatorServicer):
    async def ValidateToken(self, request, context):
        user_id = decode_token(request.token)    # raises on invalid
        return auth_pb2.TokenResponse(valid=True, user_id=user_id)

    async def CheckRegistrationQuota(self, request, context):
        # check DB counts, rate limits, etc.
        return auth_pb2.QuotaResponse(allowed=True)

async def serve():
    server = grpc.aio.server(futures.ThreadPoolExecutor(max_workers=10))
    auth_pb2_grpc.add_AuthValidatorServicer_to_server(AuthValidatorServicer(), server)
    server.add_insecure_port("[::]:50051")
    await server.start()
    await server.wait_for_termination()
```

### gRPC client in another component

```python
# app/grpc_clients.py
import grpc
from app.proto import auth_pb2, auth_pb2_grpc

_channel = grpc.aio.insecure_channel("auth-service:50051")
_stub    = auth_pb2_grpc.AuthValidatorStub(_channel)

async def validate_token(token: str) -> str:
    resp = await _stub.ValidateToken(auth_pb2.TokenRequest(token=token))
    if not resp.valid:
        raise PermissionError("Invalid token")
    return resp.user_id
```

---

## RabbitMQ — Async Messaging

Use RabbitMQ for operations that should **not block the request**: notifications, audit logs, analytics, and "something happened" broadcasts.

| Exchange / Routing Key  | Producer     | Consumers                     |
|-------------------------|--------------|-------------------------------|
| `user.registered`       | auth         | notifications, analytics, crm |
| `user.login`            | auth         | audit-log                     |
| `order.created`         | orders       | inventory, notifications      |
| `payment.completed`     | payments     | orders, notifications         |

### Publishing (producer)

```python
# app/messaging.py
import aio_pika, json, os

AMQP_URL = os.getenv("AMQP_URL", "amqp://guest:guest@rabbitmq/")

async def publish(routing_key: str, payload: dict) -> None:
    conn = await aio_pika.connect_robust(AMQP_URL)
    async with conn:
        channel  = await conn.channel()
        exchange = await channel.declare_exchange("events", aio_pika.ExchangeType.TOPIC, durable=True)
        await exchange.publish(
            aio_pika.Message(
                body=json.dumps(payload).encode(),
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            ),
            routing_key=routing_key,
        )
```

### Consuming (subscriber)

```python
# app/messaging.py  (continued)
async def start_consumer() -> None:
    conn = await aio_pika.connect_robust(AMQP_URL)
    channel  = await conn.channel()
    exchange = await channel.declare_exchange("events", aio_pika.ExchangeType.TOPIC, durable=True)
    queue    = await channel.declare_queue("notifications.user_events", durable=True)
    await queue.bind(exchange, routing_key="user.*")

    async with queue.iterator() as messages:
        async for msg in messages:
            async with msg.process():
                data = json.loads(msg.body)
                await handle_event(msg.routing_key, data)

async def handle_event(key: str, data: dict) -> None:
    if key == "user.registered":
        await send_welcome_email(data["email"])
    elif key == "user.login":
        await write_audit_log(data)
```

---

## API Gateway

Routes external HTTP traffic to internal services. Does **not** contain business logic.

```python
# gateway/main.py
import httpx
from fastapi import FastAPI, Request, Response

app = FastAPI(title="Gateway")
SERVICES = {
    "auth":    "http://auth-service:8000",
    "users":   "http://users-service:8000",
    "orders":  "http://orders-service:8000",
}

@app.api_route("/{service}/{path:path}", methods=["GET","POST","PUT","PATCH","DELETE"])
async def proxy(service: str, path: str, request: Request):
    base = SERVICES.get(service)
    if not base:
        return Response(status_code=404)
    async with httpx.AsyncClient() as client:
        resp = await client.request(
            method=request.method,
            url=f"{base}/{path}",
            headers=dict(request.headers),
            content=await request.body(),
        )
    return Response(content=resp.content, status_code=resp.status_code, headers=dict(resp.headers))
```

---

## Per-Component pyproject.toml

```toml
[project]
name = "auth-service"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi==0.115.0",
    "uvicorn[standard]==0.30.6",
    "sqlalchemy[asyncio]==2.0.35",
    "asyncpg==0.29.0",
    "pydantic[email]==2.9.2",
    "python-jose[cryptography]==3.3.0",
    "passlib[argon2]==1.7.4",
    "aio-pika==9.4.3",
    "grpcio==1.66.1",
    "grpcio-tools==1.66.1",
]

[project.optional-dependencies]
test = [
    "pytest==8.3.3",
    "pytest-asyncio==0.24.0",
    "httpx==0.27.2",
    "aiosqlite==0.20.0",
]
```

## Per-Component Dockerfile

```dockerfile
FROM python:3.12-slim AS base
WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir .

FROM base AS final
COPY app/ ./app/
EXPOSE 8000 50051
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## Testing Per Component

```python
# tests/conftest.py
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from app.main import app
from app.db import Base, get_db

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
```

**Unit tests** — isolate with mocks:
```python
# tests/unit/test_service.py
from unittest.mock import AsyncMock, patch
from app.service import AuthService

async def test_register_duplicate_email(fake_repo):
    fake_repo.get_by_email = AsyncMock(return_value=object())
    svc = AuthService(fake_repo)
    with pytest.raises(HTTPException) as exc:
        await svc.register(RegisterRequest(email="a@b.com", password="Secret1", ...))
    assert exc.value.status_code == 409
```

**Integration tests** — real in-memory DB, mock gRPC/RabbitMQ:
```python
# tests/integration/test_auth_routes.py
async def test_register_success(client):
    r = await client.post("/auth/register", json={
        "email": "user@example.com", "password": "Secret1",
        "first_name": "Ada", "last_name": "Lovelace"
    })
    assert r.status_code == 201
    assert r.json()["email"] == "user@example.com"
```

Always mock external calls (gRPC stubs, `publish()`) in tests:
```python
@pytest.fixture(autouse=True)
def mock_grpc(monkeypatch):
    monkeypatch.setattr("app.grpc_clients.validate_token", AsyncMock(return_value="uid-123"))

@pytest.fixture(autouse=True)
def mock_rabbitmq(monkeypatch):
    monkeypatch.setattr("app.messaging.publish", AsyncMock())
```

---

## docker-compose.yml

```yaml
services:
  rabbitmq:
    image: rabbitmq:3.13-management
    ports: ["5672:5672", "15672:15672"]
    healthcheck:
      test: ["CMD", "rabbitmq-diagnostics", "ping"]
      interval: 10s

  auth-service:
    build: ./components/auth
    ports: ["8001:8000", "50051:50051"]
    environment:
      DATABASE_URL: postgresql+asyncpg://postgres:postgres@postgres/auth
      AMQP_URL: amqp://guest:guest@rabbitmq/
      SECRET_KEY: ${SECRET_KEY}
    depends_on: [rabbitmq, postgres]

  users-service:
    build: ./components/users
    ports: ["8002:8000", "50052:50051"]
    environment:
      DATABASE_URL: postgresql+asyncpg://postgres:postgres@postgres/users
      AMQP_URL: amqp://guest:guest@rabbitmq/
      AUTH_GRPC: auth-service:50051
    depends_on: [rabbitmq, postgres, auth-service]

  gateway:
    build: ./gateway
    ports: ["8000:8000"]
    depends_on: [auth-service, users-service]

  postgres:
    image: postgres:16
    environment:
      POSTGRES_PASSWORD: postgres
    volumes: [pgdata:/var/lib/postgresql/data]

volumes:
  pgdata:
```

---

## Decision Guide

| Need | Use |
|------|-----|
| Token validation before serving a request | gRPC |
| Balance/quota check before a write | gRPC |
| Cross-service data fetch (must be fresh) | gRPC |
| Welcome email after registration | RabbitMQ |
| Audit log entry | RabbitMQ |
| Analytics/tracking event | RabbitMQ |
| Notify downstream of state change | RabbitMQ |

## Key Rules

- **One database schema per component** — never share tables across services
- **Each component owns its `.proto` files**; shared contracts go in `proto/` at repo root
- **Always mock gRPC stubs and `publish()` in tests** — never hit real infrastructure in unit/integration tests
- **Use `dependency_overrides`** to swap the DB session in tests, never patch SQLAlchemy internals
- **All I/O is async** — no synchronous DB or HTTP calls
- **No business logic in `api.py`** — routes call service methods only
- **Environment variables for all config** — no secrets in code