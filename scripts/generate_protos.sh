#!/usr/bin/env bash
# scripts/generate_protos.sh
# Run this from the repo root to compile all proto files into per-component pb2 stubs.
#
# Prerequisites:
#   pip install grpcio-tools
#
# Usage:
#   bash scripts/generate_protos.sh
set -euo pipefail

PROTO_DIR="$(cd "$(dirname "$0")/../proto" && pwd)"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${PYTHON:-python}"

log() { echo "▶ $*"; }
gen() {
  local proto="$1"; shift
  for out_dir in "$@"; do
    mkdir -p "$ROOT/$out_dir"
    "$PYTHON" -m grpc_tools.protoc \
      -I"$PROTO_DIR" \
      --python_out="$ROOT/$out_dir" \
      --grpc_python_out="$ROOT/$out_dir" \
      "$proto"
  done
}

# ── auth.proto ──────────────────────────────────────────────────────────────
# Server: auth
# Clients: every service that calls validate_token
log "Generating auth.proto stubs..."
gen "$PROTO_DIR/auth.proto" \
  components/auth/app \
  components/user/app \
  components/wallet/app \
  components/escrow/app \
  components/invoice/app \
  components/payment_link/app \
  components/payout/app \
  components/dispute/app \
  components/notification/app \
  components/kyc/app \
  components/webhook/app \
  components/organization/app \
  components/admin/app \
  components/bank/app \
  components/fee/app

# ── user.proto ───────────────────────────────────────────────────────────────
# Server: user
# Clients: kyc (SetKycLevel), admin (ListUsers, UpdateRole, BanUser)
log "Generating user.proto stubs..."
gen "$PROTO_DIR/user.proto" \
  components/user/app \
  components/kyc/app \
  components/admin/app

# ── wallet.proto ─────────────────────────────────────────────────────────────
# Server: wallet
# Clients: escrow, payout, dispute
log "Generating wallet.proto stubs..."
gen "$PROTO_DIR/wallet.proto" \
  components/wallet/app \
  components/escrow/app \
  components/payout/app \
  components/dispute/app

# ── escrow.proto ─────────────────────────────────────────────────────────────
# Server: escrow
# Clients: dispute
log "Generating escrow.proto stubs..."
gen "$PROTO_DIR/escrow.proto" \
  components/escrow/app \
  components/dispute/app

# ── payment_provider.proto ───────────────────────────────────────────────────
# Server: payment_provider
# Clients: escrow (create_checkout), payment_link (create_checkout), wallet (fund via provider)
log "Generating payment_provider.proto stubs..."
gen "$PROTO_DIR/payment_provider.proto" \
  components/payment_provider/app \
  components/payment_link/app \
  components/escrow/app \
  components/wallet/app

# ── notification.proto ───────────────────────────────────────────────────────
# Server: notification
log "Generating notification.proto stubs..."
gen "$PROTO_DIR/notification.proto" \
  components/notification/app

log "✅ All proto stubs generated."
