# This component IS the gRPC server, not a client.
# Other services (wallet, escrow, payout) are clients to this component.
#
# Example usage from a client service:
#
#   import grpc
#   import grpc.aio
#
#   async def create_checkout(amount, currency, metadata_json, provider):
#       async with grpc.aio.insecure_channel(PAYMENT_GRPC) as channel:
#           # stub = PaymentProviderStub(channel)  # once stubs are compiled
#           # reply = await stub.CreateCheckout(CreateCheckoutRequest(...))
#           pass
