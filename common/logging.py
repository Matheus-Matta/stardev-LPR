import logging
import re
from collections.abc import Mapping

SECRET_PATTERNS = [
    re.compile(r"(rtsp://[^:\s]+:)([^@\s]+)(@)", re.IGNORECASE),
    re.compile(r"((?:password|secret|token|key)=)([^&\s]+)", re.IGNORECASE),
    re.compile(r"((?:POSTGRES_PASSWORD|SECRET_KEY|FIELD_ENCRYPTION_KEY)=)(\S+)", re.IGNORECASE),
]


def mask_secrets(value: object) -> str:
    text = str(value)
    for pattern in SECRET_PATTERNS:
        text = pattern.sub(r"\1***\3" if pattern.groups >= 3 else r"\1***", text)
    return text


class SecretMaskingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = mask_secrets(record.msg)
        if record.args:
            if isinstance(record.args, Mapping):
                record.args = {key: mask_secrets(value) for key, value in record.args.items()}
            else:
                record.args = tuple(mask_secrets(arg) for arg in record.args)
        return True
