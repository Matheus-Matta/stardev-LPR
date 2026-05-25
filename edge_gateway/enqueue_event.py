import argparse
import json
from pathlib import Path

from edge_gateway.gateway import LocalQueue


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue-db", default="gateway_queue.sqlite3")
    parser.add_argument("--max-events", type=int, default=10000)
    parser.add_argument("--payload", required=True)
    parser.add_argument("--idempotency-key", default="")
    args = parser.parse_args()

    queue = LocalQueue(Path(args.queue_db), args.max_events)
    key = queue.enqueue(json.loads(args.payload), args.idempotency_key or None)
    print(key)


if __name__ == "__main__":
    main()

