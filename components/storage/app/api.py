"""HTTP API placeholder for storage service (gRPC is the primary surface)."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/storage", tags=["storage"])
