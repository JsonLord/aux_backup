"""One-time service credential provisioning for operators.

Usage: python -m apps.api.credentials NAME WORKSPACE [WORKSPACE ...]
"""
import json
import sys

from .store import create_store


def main(argv=None):
    argv = argv or sys.argv[1:]
    if len(argv) < 2: raise SystemExit("usage: credentials NAME WORKSPACE [WORKSPACE ...]")
    store = create_store()
    if store.backend != "postgresql": raise SystemExit("service credentials require PostgreSQL")
    print(json.dumps(store.create_service_credential(argv[0], argv[1:])))


if __name__ == "__main__": main()
