from django.conf import settings
from django.db import models


class Business(models.Model):
    name = models.CharField(max_length=160)
    legal_name = models.CharField(max_length=220, blank=True)
    document = models.CharField(max_length=40, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Tenant(models.Model):
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="tenants")
    name = models.CharField(max_length=160)
    slug = models.SlugField(max_length=180, unique=True)
    document = models.CharField(max_length=40, blank=True)
    location = models.CharField(max_length=255, blank=True)
    timezone = models.CharField(max_length=64, default="America/Sao_Paulo")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["business__name", "name"]

    def __str__(self) -> str:
        return f"{self.business} / {self.name}"


class UserTenantAccess(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        ADMIN = "admin", "Admin"
        OPERATOR = "operator", "Operator"
        VIEWER = "viewer", "Viewer"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="tenant_accesses",
    )
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="user_accesses")
    tenant = models.ForeignKey(
        Tenant,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="user_accesses",
        help_text="Blank means access to all tenants in the business.",
    )
    role = models.CharField(max_length=32, choices=Role.choices, default=Role.OPERATOR)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["user__username", "business__name", "tenant__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "business", "tenant"],
                name="unique_user_business_tenant_access",
            )
        ]

    def __str__(self) -> str:
        target = self.tenant.name if self.tenant else "all tenants"
        return f"{self.user} -> {self.business} / {target}"


class UserProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="tenant_profile",
    )
    business = models.ForeignKey(
        Business,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="admin_profiles",
    )
    is_admin = models.BooleanField(
        default=False,
        help_text="Business admin: can manage all tenants in the selected business.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["user__username"]

    def __str__(self) -> str:
        return f"{self.user} profile"
