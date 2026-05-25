import hashlib
import hmac
import json

from common.tasks import _signature


def test_webhook_signature_uses_hmac_sha256():
    body = json.dumps({"event": "plate.read"}, separators=(",", ":"), sort_keys=True).encode()
    expected = hmac.new(b"secret", body, hashlib.sha256).hexdigest()

    assert _signature("secret", body) == f"sha256={expected}"

