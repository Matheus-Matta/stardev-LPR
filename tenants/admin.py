from django.contrib import admin
from unfold.admin import ModelAdmin

from tenants.admin_mixins import (
    BusinessAdminAccessMixin,
    TenantAdminAccessMixin,
    UserAccessAdminMixin,
)
from tenants.models import Business, Tenant, UserProfile, UserTenantAccess


@admin.register(Business)
class BusinessAdmin(BusinessAdminAccessMixin, ModelAdmin):
    list_display = ("name", "document", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name", "legal_name", "document")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Tenant)
class TenantAdmin(TenantAdminAccessMixin, ModelAdmin):
    list_display = ("name", "business", "slug", "timezone", "is_active", "created_at")
    list_filter = ("business", "is_active", "timezone")
    search_fields = ("name", "slug", "document", "location", "business__name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(UserTenantAccess)
class UserTenantAccessAdmin(UserAccessAdminMixin, ModelAdmin):
    list_display = ("user", "business", "tenant", "role", "is_active")
    list_filter = ("business", "tenant", "role", "is_active")
    search_fields = ("user__username", "user__email", "business__name", "tenant__name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(UserProfile)
class UserProfileAdmin(UserAccessAdminMixin, ModelAdmin):
    superuser_manage_only = True
    list_display = ("user", "business", "is_admin", "created_at")
    list_filter = ("business", "is_admin")
    search_fields = ("user__username", "user__email", "business__name")
    readonly_fields = ("created_at", "updated_at")
