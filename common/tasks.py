import hashlib
import hmac
import json
import logging

import requests
from celery import shared_task
from django.utils import timezone

from common.models import WebhookDelivery, WebhookSubscription

logger = logging.getLogger(__name__)


@shared_task(queue="reports")
def dispatch_webhooks(event_type: str, payload: dict) -> int:
    subscriptions = WebhookSubscription.objects.filter(
        event_type=event_type,
        is_active=True,
    )
    count = 0
    for subscription in subscriptions:
        delivery = WebhookDelivery.objects.create(
            subscription=subscription,
            tenant=subscription.tenant,
            event_type=event_type,
            payload=payload,
        )
        deliver_webhook.delay(delivery.id)
        count += 1
    return count


@shared_task(bind=True, queue="reports", max_retries=5)
def deliver_webhook(self, delivery_id: int) -> None:
    delivery = WebhookDelivery.objects.select_related("subscription").get(id=delivery_id)
    delivery.attempts += 1
    delivery.save(update_fields=["attempts", "updated_at"])

    body = json.dumps(delivery.payload, separators=(",", ":"), sort_keys=True).encode()
    headers = {
        "Content-Type": "application/json",
        "X-LPR-Event": delivery.event_type,
        "X-LPR-Signature": _signature(delivery.subscription.get_secret(), body),
    }

    try:
        response = requests.post(
            delivery.subscription.url,
            data=body,
            headers=headers,
            timeout=10,
        )
        delivery.response_status_code = response.status_code
        delivery.response_body = response.text[:4000]
        response.raise_for_status()
    except Exception as exc:
        delivery.status = WebhookDelivery.Status.FAILED
        delivery.error_message = str(exc)
        delivery.save(
            update_fields=[
                "status",
                "response_status_code",
                "response_body",
                "error_message",
                "updated_at",
            ]
        )
        countdown = min((2 ** self.request.retries) * 30, 900)
        logger.warning("Retrying webhook delivery %s in %s seconds", delivery_id, countdown)
        raise self.retry(exc=exc, countdown=countdown) from exc

    delivery.status = WebhookDelivery.Status.SUCCESS
    delivery.error_message = ""
    delivery.delivered_at = timezone.now()
    delivery.save(
        update_fields=[
            "status",
            "response_status_code",
            "response_body",
            "error_message",
            "delivered_at",
            "updated_at",
        ]
    )


def _signature(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"
