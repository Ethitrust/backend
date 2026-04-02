"""
gRPC server for the Organization service.

Exposes:
  - CheckOrgMembership(OrgMembershipRequest) → OrgMembershipResponse
    - VerifySecretKey(VerifySecretKeyRequest) → VerifySecretKeyResponse

Run `bash scripts/generate_protos.sh` from repo root before starting this service.
The Dockerfile runs it automatically during build.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import uuid
from pathlib import Path

import grpc
import grpc.aio
from sqlalchemy import select

_APP_DIR = Path(__file__).resolve().parent
_PROTO_DIR = _APP_DIR.parent / "proto"
if str(_PROTO_DIR) not in sys.path:
    sys.path.insert(0, str(_PROTO_DIR))

proto_module = sys.modules.setdefault("proto", type(sys)("proto"))
proto_paths = list(getattr(proto_module, "__path__", []))
if str(_PROTO_DIR) not in proto_paths:
    proto_module.__path__ = [*proto_paths, str(_PROTO_DIR)]

logger = logging.getLogger(__name__)
GRPC_PORT = int(os.getenv("GRPC_PORT", "50051"))


import proto.organization_pb2 as organization_pb2
import proto.organization_pb2_grpc as organization_pb2_grpc
from app.db import AsyncSessionLocal, Organization, OrganizationMember
from app.repository import OrgRepository
from app.service import OrgService


class OrganizationServicer(organization_pb2_grpc.OrganizationServiceServicer):
    """Implements the Organization gRPC service."""

    async def CheckOrgMembership(
        self,
        request: organization_pb2.OrgMembershipRequest,
        context: grpc.aio.ServicerContext,
    ) -> organization_pb2.OrgMembershipExistsResponse:  # noqa: N802
        """Check if a user is a member of an organization."""
        org_id = uuid.UUID(request.org_id)
        user_id = uuid.UUID(request.user_id)

        async with AsyncSessionLocal() as session:
            r = await session.execute(
                select(OrganizationMember)
                .where(OrganizationMember.org_id == org_id)
                .where(OrganizationMember.user_id == user_id)
            )
            exists = r.scalar_one_or_none() is not None

        return organization_pb2.OrgMembershipExistsResponse(is_member=exists)

    async def CheckOrganizationExists(
        self,
        request: organization_pb2.OrganizationExistsRequest,
        context: grpc.aio.ServicerContext,
    ) -> organization_pb2.OrganizationExistsResponse:  # noqa: N802
        """Check whether an organization id exists."""
        try:
            org_id = uuid.UUID(request.org_id)
        except (ValueError, TypeError, AttributeError):
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Invalid org_id")

        async with AsyncSessionLocal() as session:
            r = await session.execute(
                select(Organization).where(Organization.id == org_id)
            )
            exists = r.scalar_one_or_none() is not None

        return organization_pb2.OrganizationExistsResponse(exists=exists)

    async def VerifySecretKey(
        self,
        request: organization_pb2.VerifySecretKeyRequest,
        context: grpc.aio.ServicerContext,
    ) -> organization_pb2.VerifySecretKeyResponse:  # noqa: N802
        """Validate an organization secret key and return org identity."""
        secret_key = request.secret_key.strip()
        if not secret_key:
            return organization_pb2.VerifySecretKeyResponse(valid=False)

        async with AsyncSessionLocal() as session:
            service = OrgService(OrgRepository(session))
            org = await service.verify_secret_key(secret_key)

        if org is None:
            return organization_pb2.VerifySecretKeyResponse(valid=False)

        return organization_pb2.VerifySecretKeyResponse(
            valid=True,
            org_id=str(org.id),
            public_key=org.public_key,
            status=org.status,
            is_test=org.public_key.startswith("pk_test_"),
        )


async def serve() -> None:
    server = grpc.aio.server()
    organization_pb2_grpc.add_OrganizationServiceServicer_to_server(
        OrganizationServicer(), server
    )
    server.add_insecure_port(f"[::]:{GRPC_PORT}")
    logger.info("Organization gRPC server starting on port %s", GRPC_PORT)
    await server.start()
    try:
        await server.wait_for_termination()
    except asyncio.CancelledError:
        await server.stop(grace=5)
        logger.info("Organization gRPC server stopped")
