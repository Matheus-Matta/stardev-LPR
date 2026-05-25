import json

from django.contrib.auth.models import AnonymousUser

from common.models import AuditLog


def get_client_ip(request) -> str | None:
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded_for:
        return forwarded_for.split(",", maxsplit=1)[0].strip()
    return request.META.get("REMOTE_ADDR")


def write_audit_log(
    request,
    action: str,
    metadata: dict | None = None,
    *,
    entity_type: str = "",
    entity_id: str = "",
    old_value: dict | None = None,
    new_value: dict | None = None,
    reason: str = "",
    tenant=None,
) -> AuditLog:
    user = getattr(request, "user", None)
    if isinstance(user, AnonymousUser) or not getattr(user, "is_authenticated", False):
        user = None

    return AuditLog.objects.create(
        action=action,
        tenant=tenant,
        user=user,
        ip_address=get_client_ip(request),
        path=getattr(request, "path", ""),
        entity_type=entity_type,
        entity_id=entity_id,
        old_value=_json_safe(old_value or {}),
        new_value=_json_safe(new_value or {}),
        reason=reason,
        metadata=_json_safe(metadata or {}),
    )


def _json_safe(value: dict) -> dict:
    return json.loads(json.dumps(value, default=str))
