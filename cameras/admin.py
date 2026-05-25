from django import forms
from django.contrib import admin
from unfold.admin import ModelAdmin

from cameras.models import Camera, Gateway
from tenants.admin_mixins import TenantScopedAdminMixin


class CameraAdminForm(forms.ModelForm):
    password = forms.CharField(required=False, widget=forms.PasswordInput(render_value=False))

    class Meta:
        model = Camera
        fields = "__all__"

    def save(self, commit=True):
        instance = super().save(commit=False)
        password = self.cleaned_data.get("password")
        if password:
            instance.set_password(password)
        if commit:
            instance.save()
            self.save_m2m()
        return instance


@admin.register(Camera)
class CameraAdmin(TenantScopedAdminMixin, ModelAdmin):
    form = CameraAdminForm
    list_display = (
        "name",
        "tenant",
        "camera_key",
        "connection_mode",
        "direction_default",
        "gateway",
        "timezone",
        "is_active",
        "last_seen_at",
    )
    list_filter = ("tenant", "connection_mode", "direction_default", "is_active", "timezone")
    search_fields = ("name", "camera_key", "host", "rtsp_path", "username", "location")
    readonly_fields = ("created_at", "updated_at", "masked_rtsp_url")
    exclude = ("password_encrypted", "ingest_token_hash")


@admin.register(Gateway)
class GatewayAdmin(TenantScopedAdminMixin, ModelAdmin):
    list_display = (
        "name",
        "tenant",
        "gateway_key",
        "status",
        "pending_events",
        "last_seen_at",
        "is_active",
    )
    list_filter = ("tenant", "status", "is_active")
    search_fields = ("name", "gateway_key", "location", "version")
    readonly_fields = ("created_at", "updated_at", "last_seen_at")
    exclude = ("token_hash",)
