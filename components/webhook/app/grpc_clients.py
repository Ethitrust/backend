import logging
import os
import sys
from pathlib import Path
from typing import Optional

import grpc

logger = logging.getLogger(__name__)

AUTH_GRPC_HOST = os.getenv("AUTH_GRPC_HOST", "auth-service:50051")

_APP_DIR = Path(__file__).resolve().parent
_PROTO_DIR = _APP_DIR.parent / "proto"
if str(_PROTO_DIR) not in sys.path:
    sys.path.insert(0, str(_PROTO_DIR))

proto_module = sys.modules.setdefault("proto", type(sys)("proto"))
proto_paths = list(getattr(proto_module, "__path__", []))
if str(_PROTO_DIR) not in proto_paths:
    proto_module.__path__ = [*proto_paths, str(_PROTO_DIR)]


async def validate_token(token: str) -> Optional[dict]:
    """
    Call the Auth gRPC service to validate a JWT and return its claims.
    Returns None if the token is invalid or the gRPC call fails.
    """
    try:
        # Import generated stubs — generated from proto/auth.proto
        import proto.auth_pb2 as auth_pb2
        import proto.auth_pb2_grpc as auth_pb2_grpc

        async with grpc.aio.insecure_channel(AUTH_GRPC_HOST) as channel:
            stub = auth_pb2_grpc.AuthServiceStub(channel)
            request = auth_pb2.ValidateTokenRequest(token=token)
            response = await stub.ValidateToken(request)
            if response.valid:
                return {
                    "user_id": response.user_id,
                    "org_id": response.org_id,
                    "roles": list(response.roles),
                }
            return None
    except Exception as exc:
        logger.warning("Token validation gRPC call failed: %s", exc)
        return None
