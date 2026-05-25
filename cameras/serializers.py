from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from rest_framework import serializers

from cameras.models import Camera, Gateway
from tenants.utils import user_can_access_tenant, validate_tenant_for_user


class CameraSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)
    rotate_token = serializers.BooleanField(write_only=True, required=False, default=False)
    new_ingest_token = serializers.CharField(read_only=True)
    masked_rtsp_url = serializers.CharField(read_only=True)
    gateway_name = serializers.CharField(source="gateway.name", read_only=True)

    class Meta:
        model = Camera
        fields = [
            "id",
            "tenant",
            "name",
            "camera_key",
            "connection_mode",
            "direction_default",
            "location",
            "gateway",
            "gateway_name",
            "host",
            "port",
            "rtsp_path",
            "username",
            "password",
            "rotate_token",
            "new_ingest_token",
            "masked_rtsp_url",
            "timezone",
            "is_active",
            "last_seen_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "camera_key",
            "new_ingest_token",
            "masked_rtsp_url",
            "last_seen_at",
            "created_at",
            "updated_at",
        ]

    def create(self, validated_data):
        password = validated_data.pop("password", "")
        rotate_token = validated_data.pop("rotate_token", True)
        camera = Camera(**validated_data)
        if password:
            camera.set_password(password)
        camera.save()
        if rotate_token:
            camera.new_ingest_token = camera.rotate_ingest_token()
        return camera

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        rotate_token = validated_data.pop("rotate_token", False)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        if password is not None:
            instance.set_password(password)
        instance.save()
        if rotate_token:
            instance.new_ingest_token = instance.rotate_ingest_token()
        return instance

    def validate(self, attrs):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            tenant = attrs.get("tenant", getattr(self.instance, "tenant", None))
            validate_tenant_for_user(request.user, tenant)
            gateway = attrs.get("gateway", getattr(self.instance, "gateway", None))
            if gateway:
                if gateway.tenant_id and not user_can_access_tenant(
                    request.user,
                    gateway.tenant_id,
                ):
                    raise serializers.ValidationError(
                        {"gateway": "Gateway not allowed for this user."},
                    )
                if tenant and gateway.tenant_id and gateway.tenant_id != tenant.id:
                    raise serializers.ValidationError(
                        {"gateway": "Gateway must belong to the selected tenant."},
                    )
        return attrs

    def validate_timezone(self, value):
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise serializers.ValidationError("Invalid timezone.") from exc
        return value


class GatewaySerializer(serializers.ModelSerializer):
    rotate_token = serializers.BooleanField(write_only=True, required=False, default=False)
    new_token = serializers.CharField(read_only=True)

    class Meta:
        model = Gateway
        fields = [
            "id",
            "tenant",
            "name",
            "gateway_key",
            "location",
            "status",
            "last_seen_at",
            "version",
            "pending_events",
            "cameras_online",
            "cameras_offline",
            "is_active",
            "rotate_token",
            "new_token",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "gateway_key",
            "status",
            "last_seen_at",
            "pending_events",
            "cameras_online",
            "cameras_offline",
            "new_token",
            "created_at",
            "updated_at",
        ]

    def create(self, validated_data):
        rotate_token = validated_data.pop("rotate_token", True)
        gateway = Gateway.objects.create(**validated_data)
        if rotate_token:
            gateway.new_token = gateway.rotate_token()
        return gateway

    def update(self, instance, validated_data):
        rotate_token = validated_data.pop("rotate_token", False)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        if rotate_token:
            instance.new_token = instance.rotate_token()
        return instance

    def validate(self, attrs):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            tenant = attrs.get("tenant", getattr(self.instance, "tenant", None))
            validate_tenant_for_user(request.user, tenant)
        return attrs
