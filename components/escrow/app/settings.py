"""Runtime settings for the Escrow service."""

from __future__ import annotations

import os

PLATFORM_FEE_PERCENT: float = float(os.getenv("PLATFORM_FEE_PERCENT", "1.5"))
MIN_FEE_AMOUNT: int = int(os.getenv("MIN_FEE_AMOUNT", "100"))
MAX_FEE_AMOUNT: int = int(os.getenv("MAX_FEE_AMOUNT", "500000"))

DEFAULT_INSPECTION_PERIOD_HOURS: int = int(
    os.getenv("ESCROW_DEFAULT_INSPECTION_PERIOD_HOURS", "24")
)
DEFAULT_DISPUTE_WINDOW_HOURS: int = int(
    os.getenv("ESCROW_DEFAULT_DISPUTE_WINDOW_HOURS", "72")
)
DEFAULT_MILESTONE_INSPECTION_HOURS: int = int(
    os.getenv("ESCROW_DEFAULT_MILESTONE_INSPECTION_HOURS", "24")
)

INVITATION_EXPIRY_HOURS: int = int(os.getenv("ESCROW_INVITATION_EXPIRY_HOURS", "168"))
