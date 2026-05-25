import secrets

from django.contrib.auth import get_user_model
from rest_framework import serializers

from tenants.models import Business, Tenant, UserTenantAccess
from tenants.utils import is_business_admin


class BusinessSerializer(serializers.ModelSerializer):
    class Meta:
        model = Business
        fields = "__all__"
        read_only_fields = ["id", "created_at", "updated_at"]


class TenantSerializer(serializers.ModelSerializer):
    business_name = serializers.CharField(source="business.name", read_only=True)

    class Meta:
        model = Tenant
        fields = "__all__"
        read_only_fields = ["id", "created_at", "updated_at", "business_name"]


class UserTenantAccessSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True)
    business_name = serializers.CharField(source="business.name", read_only=True)
    tenant_name = serializers.CharField(source="tenant.name", read_only=True)

    class Meta:
        model = UserTenantAccess
        fields = "__all__"
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "username",
            "business_name",
            "tenant_name",
        ]


class ManagedTenantAccessSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True)
    email = serializers.EmailField(source="user.email", read_only=True)
    business_name = serializers.CharField(source="business.name", read_only=True)
    tenant_name = serializers.CharField(source="tenant.name", read_only=True)

    class Meta:
        model = UserTenantAccess
        fields = [
            "id",
            "user",
            "username",
            "email",
            "business",
            "business_name",
            "tenant",
            "tenant_name",
            "role",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "username",
            "email",
            "business_name",
            "tenant_name",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        request = self.context["request"]
        business = attrs.get("business") or getattr(self.instance, "business", None)
        tenant = attrs.get("tenant") or getattr(self.instance, "tenant", None)
        if tenant and business and tenant.business_id != business.id:
            raise serializers.ValidationError("Tenant does not belong to the selected business.")
        if not is_business_admin(request.user, business.id):
            raise serializers.ValidationError("You cannot manage this business.")
        return attrs


class GrantTenantAccessSerializer(serializers.Serializer):
    business = serializers.PrimaryKeyRelatedField(queryset=Business.objects.filter(is_active=True))
    tenant = serializers.PrimaryKeyRelatedField(
        queryset=Tenant.objects.filter(is_active=True),
        required=False,
        allow_null=True,
    )
    role = serializers.ChoiceField(choices=UserTenantAccess.Role.choices)
    username = serializers.CharField(required=False, allow_blank=True)
    email = serializers.EmailField()
    password = serializers.CharField(required=False, allow_blank=True, write_only=True)
    first_name = serializers.CharField(required=False, allow_blank=True)
    last_name = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        request = self.context["request"]
        business = attrs["business"]
        tenant = attrs.get("tenant")
        if tenant and tenant.business_id != business.id:
            raise serializers.ValidationError("Tenant does not belong to the selected business.")
        if not is_business_admin(request.user, business.id):
            raise serializers.ValidationError("You cannot grant access for this business.")
        return attrs

    def create(self, validated_data):
        user_model = get_user_model()
        email = validated_data["email"].lower()
        username = validated_data.get("username") or email
        password = validated_data.get("password") or secrets.token_urlsafe(12)
        user, created = user_model.objects.get_or_create(
            username=username,
            defaults={
                "email": email,
                "first_name": validated_data.get("first_name", ""),
                "last_name": validated_data.get("last_name", ""),
                "is_active": True,
            },
        )
        if created:
            user.set_password(password)
            user.save()
        elif email and user.email != email:
            user.email = email
            user.save(update_fields=["email"])

        access, _ = UserTenantAccess.objects.update_or_create(
            user=user,
            business=validated_data["business"],
            tenant=validated_data.get("tenant"),
            defaults={
                "role": validated_data["role"],
                "is_active": True,
            },
        )
        access.generated_password = password if created else ""
        return access

    def to_representation(self, instance):
        data = ManagedTenantAccessSerializer(instance).data
        data["generated_password"] = getattr(instance, "generated_password", "")
        return data
