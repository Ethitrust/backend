.PHONY: protos protos-check

protos:
	python scripts/generate_protos.py

protos-check:
	python scripts/generate_protos.py
	git diff --exit-code -- '*.proto' '*_pb2.py' '*_pb2_grpc.py'
