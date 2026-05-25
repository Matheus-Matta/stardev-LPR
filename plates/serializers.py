from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.utils import timezone
from rest_framework import serializers

from cameras.models import Camera
from plates.access import normalize_plate
from plates.models import AccessEvent, Alert, PlateEvent, PlateRegistry, VehiclePresence
from plates.validators import sanitize_uploaded_image
from tenants.utils import user_can_access_tenant, validate_tenant_for_user


class PlateUploadSerializer(serializers.Serializer):
    camera_id = serializers.PrimaryKeyRelatedField(queryset=Camera.objects.filter(is_active=True))
    event_type = serializers.ChoiceField(
        choices=PlateEvent.EventType.choices,
        default=PlateEvent.EventType.UNKNOWN,
    )
    image = serializers.ImageField()

    def validate_image(self, value):
        return sanitize_uploaded_image(value)

    def validate_camera_id(self, value):
        request = self.context.get("request")
        if (
            request
            and request.user.is_authenticated
            and value.tenant_id
            and not user_can_access_tenant(request.user, value.tenant_id)
        ):
            raise serializers.ValidationError("Camera not allowed for this user.")
        return value

    def create(self, validated_data):
        return PlateEvent.objects.create(
            camera=validated_data["camera_id"],
            tenant=validated_data["camera_id"].tenant,
            event_type=validated_data["event_type"],
            image=validated_data["image"],
        )


class PlateEventSerializer(serializers.ModelSerializer):
    camera_name = serializers.CharField(source="camera.name", read_only=True)
    captured_at_local = serializers.SerializerMethodField()

    class Meta:
        model = PlateEvent
        fields = [
            "id",
            "camera",
            "tenant",
            "camera_name",
            "event_type",
            "image",
            "captured_at",
            "captured_at_local",
            "plate_text",
            "confidence",
            "status",
            "raw_payload",
            "pipeline_metadata",
            "error_message",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_captured_at_local(self, obj) -> str:
        try:
            camera_tz = ZoneInfo(obj.camera.timezone)
        except ZoneInfoNotFoundError:
            camera_tz = ZoneInfo("UTC")
        return timezone.localtime(obj.captured_at, camera_tz).isoformat()


class PlateRegistrySerializer(serializers.ModelSerializer):
    class Meta:
        model = PlateRegistry
        fields = [
            "id",
            "tenant",
            "plate",
            "normalized_plate",
            "list_type",
            "status",
            "owner_name",
            "owner_document",
            "vehicle_model",
            "vehicle_color",
            "vehicle_type",
            "valid_from",
            "valid_until",
            "block_reason",
            "risk_level",
            "notes",
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "normalized_plate",
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
        ]

    def validate_plate(self, value):
        normalized = normalize_plate(value)
        if not normalized:
            raise serializers.ValidationError("Plate is required.")
        return value

    def validate(self, attrs):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            tenant = attrs.get("tenant", getattr(self.instance, "tenant", None))
            validate_tenant_for_user(request.user, tenant)
        return super().validate(attrs)

    def create(self, validated_data):
        request = self.context.get("request")
        validated_data["normalized_plate"] = normalize_plate(validated_data["plate"])
        if request and request.user.is_authenticated:
            validated_data["created_by"] = request.user
            validated_data["updated_by"] = request.user
        return super().create(validated_data)

    def update(self, instance, validated_data):
        request = self.context.get("request")
        if "plate" in validated_data:
            validated_data["normalized_plate"] = normalize_plate(validated_data["plate"])
        if request and request.user.is_authenticated:
            validated_data["updated_by"] = request.user
        return super().update(instance, validated_data)


class AccessEventSerializer(serializers.ModelSerializer):
    camera_name = serializers.CharField(source="camera.name", read_only=True)
    gateway_name = serializers.CharField(source="gateway.name", read_only=True)

    class Meta:
        model = AccessEvent
        fields = [
            "id",
            "event_uuid",
            "tenant",
            "camera",
            "camera_name",
            "gateway",
            "gateway_name",
            "plate_event",
            "plate_registry",
            "plate_text",
            "normalized_plate",
            "list_type_result",
            "decision",
            "decision_reason",
            "movement_type",
            "confidence",
            "captured_at",
            "received_at",
            "processed_at",
            "image",
            "crop_image",
            "raw_payload",
            "status",
            "error_message",
            "idempotency_key",
            "reviewed_at",
            "reviewed_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class AccessEventCorrectionSerializer(serializers.Serializer):
    plate = serializers.CharField(max_length=16)
    reason = serializers.CharField(required=False, allow_blank=True)


class AccessEventDecisionSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=AccessEvent.Decision.choices)
    reason = serializers.CharField(required=False, allow_blank=True)


class VehiclePresenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = VehiclePresence
        fields = "__all__"
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate(self, attrs):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            tenant = attrs.get("tenant", getattr(self.instance, "tenant", None))
            validate_tenant_for_user(request.user, tenant)
            plate_registry = attrs.get(
                "plate_registry",
                getattr(self.instance, "plate_registry", None),
            )
            if (
                plate_registry
                and tenant
                and plate_registry.tenant_id
                and plate_registry.tenant_id != tenant.id
            ):
                raise serializers.ValidationError(
                    {"plate_registry": "Plate registry must belong to the selected tenant."},
                )
        return super().validate(attrs)


class VehiclePresenceCorrectionSerializer(serializers.Serializer):
    current_status = serializers.ChoiceField(choices=VehiclePresence.CurrentStatus.choices)
    reason = serializers.CharField()


class AlertSerializer(serializers.ModelSerializer):
    class Meta:
        model = Alert
        fields = "__all__"
        read_only_fields = ["id", "created_at", "updated_at", "resolved_by", "resolved_at"]

    def validate(self, attrs):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            tenant = attrs.get("tenant", getattr(self.instance, "tenant", None))
            validate_tenant_for_user(request.user, tenant)
        return super().validate(attrs)


class AlertResolveSerializer(serializers.Serializer):
    notes = serializers.CharField(required=False, allow_blank=True)
