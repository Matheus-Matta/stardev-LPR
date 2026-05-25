from rest_framework import serializers

from common.models import (
    AIModelArtifact,
    DataProcessingRecord,
    DataSubjectRequest,
    DeadLetterTask,
    SecurityIncident,
    WebhookDelivery,
    WebhookSubscription,
)
from tenants.utils import validate_tenant_for_user


class TenantValidatedSerializerMixin:
    def validate(self, attrs):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            tenant = attrs.get("tenant", getattr(self.instance, "tenant", None))
            validate_tenant_for_user(request.user, tenant)
        return super().validate(attrs)


class DeadLetterTaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeadLetterTask
        fields = [
            "id",
            "tenant",
            "task_name",
            "task_id",
            "queue",
            "payload",
            "exception_class",
            "exception_message",
            "retries",
            "status",
            "reprocessed_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class WebhookSubscriptionSerializer(TenantValidatedSerializerMixin, serializers.ModelSerializer):
    secret = serializers.CharField(write_only=True, required=False, allow_blank=True)
    has_secret = serializers.SerializerMethodField()

    class Meta:
        model = WebhookSubscription
        fields = [
            "id",
            "tenant",
            "url",
            "event_type",
            "secret",
            "has_secret",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "has_secret", "created_at", "updated_at"]

    def get_has_secret(self, obj) -> bool:
        return bool(obj.secret_encrypted)

    def create(self, validated_data):
        secret = validated_data.pop("secret", "")
        instance = WebhookSubscription(**validated_data)
        if secret:
            instance.set_secret(secret)
        instance.save()
        return instance

    def update(self, instance, validated_data):
        secret = validated_data.pop("secret", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        if secret is not None:
            instance.set_secret(secret)
        instance.save()
        return instance


class WebhookDeliverySerializer(serializers.ModelSerializer):
    subscription_url = serializers.URLField(source="subscription.url", read_only=True)

    class Meta:
        model = WebhookDelivery
        fields = [
            "id",
            "tenant",
            "subscription",
            "subscription_url",
            "event_type",
            "payload",
            "status",
            "response_status_code",
            "response_body",
            "error_message",
            "attempts",
            "created_at",
            "delivered_at",
            "updated_at",
        ]
        read_only_fields = fields


class AIModelArtifactSerializer(TenantValidatedSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = AIModelArtifact
        fields = [
            "id",
            "tenant",
            "kind",
            "version",
            "storage_uri",
            "file_sha256",
            "baseline_metrics",
            "notes",
            "is_active",
            "promoted_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "is_active", "promoted_at", "created_at", "updated_at"]


class DataProcessingRecordSerializer(TenantValidatedSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = DataProcessingRecord
        fields = "__all__"
        read_only_fields = ["id", "created_at", "updated_at"]


class DataSubjectRequestSerializer(TenantValidatedSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = DataSubjectRequest
        fields = "__all__"
        read_only_fields = ["id", "created_at", "updated_at"]


class SecurityIncidentSerializer(TenantValidatedSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = SecurityIncident
        fields = "__all__"
        read_only_fields = ["id", "created_at", "updated_at"]
