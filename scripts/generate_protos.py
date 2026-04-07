"""Cross-platform protobuf code generation for Ethitrust services.

Usage:
  python scripts/generate_protos.py

Environment:
  PYTHON=python3.12  # optional, defaults to current interpreter
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROTO_DIR = ROOT / "proto"
PYTHON_BIN = os.getenv("PYTHON", sys.executable)


PROTO_TARGETS: dict[str, list[str]] = {
    # Server: auth | Clients: every service that validates token
    "auth.proto": [
        "components/auth/proto",
        "components/user/proto",
        "components/wallet/proto",
        "components/escrow/proto",
        "components/payout/proto",
        "components/dispute/proto",
        "components/notification/proto",
        "components/audit/proto",
        "components/kyc/proto",
        "components/webhook/proto",
        "components/organization/proto",
        "components/admin/proto",
        # "components/bank/proto",
        "components/fee/proto",
    ],
    # Server: user | Clients: kyc, admin
    "user.proto": [
        "components/user/proto",
        "components/kyc/proto",
        "components/admin/proto",
        "components/auth/proto",
        "components/escrow/proto",
    ],
    # Server: wallet | Clients: escrow, payout, dispute
    "wallet.proto": [
        "components/wallet/proto",
        "components/escrow/proto",
        "components/payout/proto",
        "components/dispute/proto",
    ],
    # Server: escrow | Clients: dispute
    "escrow.proto": [
        "components/escrow/proto",
        "components/dispute/proto",
        "components/auth/proto",
    ],
    # Server: payment_provider | Clients: payment_link, escrow, wallet
    "payment_provider.proto": [
        "components/payment_provider/proto",
        "components/escrow/proto",
        "components/wallet/proto",
        "components/payout/proto",
    ],
    # Server: notification
    "notification.proto": ["components/notification/proto"],
    # Server: organization | Clients: every service that has org-scoped operations
    "organization.proto": [
        "components/organization/proto",
        "components/escrow/proto",
        "components/payout/proto",
        "components/dispute/proto",
        "components/notification/proto",
        "components/audit/proto",
        "components/kyc/proto",
        "components/webhook/proto",
    ],
    # Server: storage | Clients: kyc (initial consumer)
    "storage.proto": [
        "components/storage/proto",
        "components/kyc/proto",
    ],
    # Server: payout | Clients: admin
    "payout.proto": [
        "components/payout/proto",
        "components/admin/proto",
    ],
    # Server: dispute | Clients: admin
    "dispute.proto": [
        "components/dispute/proto",
        "components/admin/proto",
    ],
    # Server: fee | Clients: admin
    "fee.proto": [
        "components/fee/proto",
        "components/admin/proto",
    ],
    # Server: audit | Clients: admin
    "audit.proto": [
        "components/audit/proto",
        "components/admin/proto",
    ],
}


def run_protoc(proto_file: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        PYTHON_BIN,
        "-m",
        "grpc_tools.protoc",
        f"-I{PROTO_DIR}",
        f"--python_out={out_dir}",
        f"--grpc_python_out={out_dir}",
        str(proto_file),
    ]
    subprocess.run(cmd, check=True)

    grpc_file = out_dir / f"{proto_file.stem}_pb2_grpc.py"
    if grpc_file.exists():
        content = grpc_file.read_text(encoding="utf-8")
        old_import = f"import {proto_file.stem}_pb2 as"
        new_import = f"import proto.{proto_file.stem}_pb2 as"
        if old_import in content:
            grpc_file.write_text(
                content.replace(old_import, new_import),
                encoding="utf-8",
            )


def main() -> int:
    if not PROTO_DIR.exists():
        print(f"❌ Proto directory not found: {PROTO_DIR}")
        return 1

    print("▶ Generating protobuf stubs...")
    for proto_name, targets in PROTO_TARGETS.items():
        proto_file = PROTO_DIR / proto_name
        if not proto_file.exists():
            print(f"⚠ Skipping missing proto: {proto_file}")
            continue

        print(f"  • {proto_name}")
        for target in targets:
            run_protoc(proto_file, ROOT / target)

    print("✅ All proto stubs generated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
