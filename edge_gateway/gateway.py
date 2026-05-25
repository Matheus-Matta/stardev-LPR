import argparse
import json
import sqlite3
import time
import uuid
from pathlib import Path

import requests


class LocalQueue:
    def __init__(self, path: Path, max_events: int):
        self.path = path
        self.max_events = max_events
        self.connection = sqlite3.connect(path)
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                idempotency_key TEXT UNIQUE NOT NULL,
                payload TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                sent_at INTEGER
            )
            """
        )
        self.connection.commit()

    def enqueue(self, payload: dict, idempotency_key: str | None = None) -> str:
        self._trim()
        key = idempotency_key or str(uuid.uuid4())
        self.connection.execute(
            "INSERT OR IGNORE INTO events (idempotency_key, payload, created_at) VALUES (?, ?, ?)",
            (key, json.dumps(payload), int(time.time())),
        )
        self.connection.commit()
        return key

    def pending(self) -> list[tuple[int, str, dict]]:
        rows = self.connection.execute(
            """
            SELECT id, idempotency_key, payload
            FROM events
            WHERE sent_at IS NULL
            ORDER BY id
            LIMIT 100
            """
        ).fetchall()
        return [(row[0], row[1], json.loads(row[2])) for row in rows]

    def mark_sent(self, row_id: int) -> None:
        self.connection.execute(
            "UPDATE events SET sent_at = ? WHERE id = ?",
            (int(time.time()), row_id),
        )
        self.connection.commit()

    def pending_count(self) -> int:
        row = self.connection.execute(
            "SELECT COUNT(*) FROM events WHERE sent_at IS NULL"
        ).fetchone()
        return int(row[0])

    def _trim(self) -> None:
        row = self.connection.execute(
            "SELECT COUNT(*) FROM events WHERE sent_at IS NULL"
        ).fetchone()
        overflow = int(row[0]) - self.max_events
        if overflow > 0:
            self.connection.execute(
                """
                DELETE FROM events
                WHERE id IN (
                    SELECT id FROM events WHERE sent_at IS NULL ORDER BY id LIMIT ?
                )
                """,
                (overflow,),
            )
            self.connection.commit()


def flush_queue(args, queue: LocalQueue) -> None:
    url = f"{args.server_url.rstrip('/')}/api/v1/ingest/gateways/{args.gateway_key}/events/"
    for row_id, idempotency_key, payload in queue.pending():
        response = requests.post(
            url,
            json=payload,
            headers={
                "X-Gateway-Token": args.gateway_token,
                "Idempotency-Key": idempotency_key,
            },
            timeout=10,
        )
        if response.status_code >= 500:
            return
        response.raise_for_status()
        queue.mark_sent(row_id)


def heartbeat(args, queue: LocalQueue) -> None:
    url = f"{args.server_url.rstrip('/')}/api/v1/ingest/gateways/{args.gateway_key}/heartbeat/"
    requests.post(
        url,
        json={
            "version": "edge-gateway-0.1",
            "pending_events": queue.pending_count(),
            "cameras_online": args.cameras_online,
            "cameras_offline": args.cameras_offline,
        },
        headers={"X-Gateway-Token": args.gateway_token},
        timeout=10,
    ).raise_for_status()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server-url", required=True)
    parser.add_argument("--gateway-key", required=True)
    parser.add_argument("--gateway-token", required=True)
    parser.add_argument("--queue-db", default="gateway_queue.sqlite3")
    parser.add_argument("--retry-interval", type=int, default=15)
    parser.add_argument("--heartbeat-interval", type=int, default=30)
    parser.add_argument("--max-events", type=int, default=10000)
    parser.add_argument("--cameras-online", type=int, default=0)
    parser.add_argument("--cameras-offline", type=int, default=0)
    args = parser.parse_args()

    queue = LocalQueue(Path(args.queue_db), args.max_events)
    next_heartbeat = 0.0
    while True:
        try:
            flush_queue(args, queue)
            if time.time() >= next_heartbeat:
                heartbeat(args, queue)
                next_heartbeat = time.time() + args.heartbeat_interval
        except requests.RequestException as exc:
            print(f"gateway sync failed: {exc}")
        time.sleep(args.retry_interval)


if __name__ == "__main__":
    main()
