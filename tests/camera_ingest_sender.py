"""
Send local plate images to the camera ingest endpoint.

Examples:

    python tests/camera_ingest_sender.py --camera-key abc --token secret

    python tests/camera_ingest_sender.py ^
      --base-url http://127.0.0.1:8000 ^
      --camera-key abc ^
      --token secret ^
      --interval 2 ^
      --count 10

By default this script sends multipart/form-data with the field name `image`.
It does not send `plate`, so the API can exercise the OCR/PlateEvent flow.
Use `--send-plate-from-filename` if you want to send the plate value too.
"""

from __future__ import annotations

import argparse
import mimetypes
import random
import re
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests


DEFAULT_IMAGE_DIR = Path(__file__).resolve().parent / "image"
DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT_SECONDS = 20


def main() -> int:
    args = parse_args()
    images = image_paths(args.image_dir, args.image)
    endpoint = ingest_url(args.base_url, args.camera_key)

    print(f"Endpoint: {endpoint}")
    print(f"Images: {len(images)} file(s)")
    print(f"Mode: {'infinite' if args.count == 0 else f'{args.count} request(s)'}")
    print("Press Ctrl+C to stop.\n")

    sent = 0
    try:
        while args.count == 0 or sent < args.count:
            image_path = images[sent % len(images)]
            payload = build_payload(args, image_path)
            headers = build_headers(args)
            response = send_image(endpoint, image_path, payload, headers, args.timeout)
            sent += 1
            print_result(sent, image_path, payload, response)

            if args.count == 0 or sent < args.count:
                time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nStopped by user.")
        return 130

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Send local images to /api/v1/ingest/cameras/{camera_key}/events/.",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"Server base URL. Default: {DEFAULT_BASE_URL}",
    )
    parser.add_argument(
        "--camera-key",
        required=True,
        help="Camera public key used in the ingest URL.",
    )
    parser.add_argument(
        "--token",
        default="",
        help="Camera ingest token. Sent as X-Camera-Token when provided.",
    )
    parser.add_argument(
        "--image-dir",
        type=Path,
        default=DEFAULT_IMAGE_DIR,
        help=f"Directory with images to cycle. Default: {DEFAULT_IMAGE_DIR}",
    )
    parser.add_argument(
        "--image",
        action="append",
        type=Path,
        default=[],
        help="Specific image path. Can be repeated. Overrides --image-dir when provided.",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Seconds between requests. Default: 1.0",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=0,
        help="How many requests to send. Use 0 for infinite. Default: 0",
    )
    parser.add_argument(
        "--direction",
        choices=["entry", "exit", "unknown", "random"],
        default="entry",
        help="Movement direction. Default: entry",
    )
    parser.add_argument(
        "--confidence",
        type=float,
        default=None,
        help="Optional fixed confidence value, for example 0.95.",
    )
    parser.add_argument(
        "--send-plate-from-filename",
        action="store_true",
        help="Extract plate from filenames like plate_ABC1D23.png and send it in payload.",
    )
    parser.add_argument(
        "--id-prefix",
        default="local-camera-test",
        help="Prefix for Idempotency-Key. Default: local-camera-test",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"Request timeout in seconds. Default: {DEFAULT_TIMEOUT_SECONDS}",
    )
    return parser.parse_args()


def image_paths(image_dir: Path, explicit_images: list[Path]) -> list[Path]:
    if explicit_images:
        images = [path.resolve() for path in explicit_images]
    else:
        images = sorted(
            path.resolve()
            for path in image_dir.glob("*")
            if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
        )

    missing = [str(path) for path in images if not path.exists()]
    if missing:
        raise SystemExit(f"Image file not found: {', '.join(missing)}")
    if not images:
        raise SystemExit(f"No images found in {image_dir}")
    return images


def ingest_url(base_url: str, camera_key: str) -> str:
    return (
        base_url.rstrip("/")
        + f"/api/v1/ingest/cameras/{camera_key}/events/"
    )


def build_headers(args: argparse.Namespace) -> dict[str, str]:
    headers = {
        "Idempotency-Key": f"{args.id_prefix}-{uuid.uuid4().hex}",
    }
    if args.token:
        headers["X-Camera-Token"] = args.token
    return headers


def build_payload(args: argparse.Namespace, image_path: Path) -> dict[str, str]:
    payload = {
        "direction": choose_direction(args.direction),
        "captured_at": datetime.now(ZoneInfo("America/Sao_Paulo")).isoformat(),
    }

    if args.confidence is not None:
        payload["confidence"] = str(args.confidence)

    if args.send_plate_from_filename:
        plate = plate_from_filename(image_path)
        if plate:
            payload["plate"] = plate

    return payload


def choose_direction(direction: str) -> str:
    if direction == "random":
        return random.choice(["entry", "exit"])
    return direction


def plate_from_filename(path: Path) -> str:
    match = re.search(r"plate_([A-Za-z0-9]+)", path.stem)
    return match.group(1).upper() if match else ""


def send_image(
    endpoint: str,
    image_path: Path,
    payload: dict[str, str],
    headers: dict[str, str],
    timeout: float,
) -> requests.Response:
    content_type = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
    with image_path.open("rb") as image_file:
        files = {
            "image": (image_path.name, image_file, content_type),
        }
        return requests.post(
            endpoint,
            data=payload,
            files=files,
            headers=headers,
            timeout=timeout,
        )


def print_result(
    index: int,
    image_path: Path,
    payload: dict[str, str],
    response: requests.Response,
) -> None:
    body = safe_json(response)
    direction = payload.get("direction", "")
    plate = payload.get("plate", "OCR")
    print(
        f"[{index}] {response.status_code} image={image_path.name} "
        f"direction={direction} plate={plate} response={body}"
    )


def safe_json(response: requests.Response):
    try:
        return response.json()
    except ValueError:
        return response.text[:500]


if __name__ == "__main__":
    sys.exit(main())
