"""Runtime settings for the Fee service."""

from __future__ import annotations

import os

PLATFORM_FEE_PERCENT: float = float(os.getenv("PLATFORM_FEE_PERCENT", "1.5"))
MIN_FEE_AMOUNT: int = int(os.getenv("MIN_FEE_AMOUNT", "100"))
MAX_FEE_AMOUNT: int = int(os.getenv("MAX_FEE_AMOUNT", "1000"))
ADMIN_GRPC_TIMEOUT_SECONDS: float = float(os.getenv("ADMIN_GRPC_TIMEOUT_SECONDS", "1.0"))
