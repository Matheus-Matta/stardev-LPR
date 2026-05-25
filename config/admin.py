from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group, User
from unfold.admin import ModelAdmin
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm

from tenants.admin_mixins import ScopedInlineMixin, scoped_queryset_for_admin
from tenants.models import UserProfile, UserTenantAccess
from tenants.utils import business_ids_administered_by, user_can_access_object

admin.site.unregister(User)
admin.site.unregister(Group)


class UserProfileInline(ScopedInlineMixin, admin.StackedInline):
    model = UserProfile
    can_delete = False
    max_num = 1
    fields = ("business", "is_admin", "created_at", "updated_at")
    readonly_fields = ("created_at", "updated_at")

    def has_add_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser


class UserTenantAccessInline(ScopedInlineMixin, admin.TabularInline):
    model = UserTenantAccess
    extra = 0
    fields = ("business", "tenant", "role", "is_active", "created_at", "updated_at")
    readonly_fields = ("created_at", "updated_at")

    def has_add_permission(self, request, obj=None):
        return request.user.is_superuser or business_ids_administered_by(request.user).exists()

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser or business_ids_administered_by(request.user).exists()

    def has_delete_permission(self, request, obj=None):
        return self.has_change_permission(request, obj)


@admin.register(User)
class UserAdmin(BaseUserAdmin, ModelAdmin):
    form = UserChangeForm
    add_form = UserCreationForm
    change_password_form = AdminPasswordChangeForm
    inlines = (UserProfileInline, UserTenantAccessInline)

    def get_queryset(self, request):
        return scoped_queryset_for_admin(super().get_queryset(request), request.user)

    def has_module_permission(self, request):
        return bool(request.user and request.user.is_active and request.user.is_staff)

    def has_view_permission(self, request, obj=None):
        if not self.has_module_permission(request):
            return False
        return obj is None or user_can_access_object(request.user, obj)

    def has_add_permission(self, request):
        return request.user.is_superuser or business_ids_administered_by(request.user).exists()

    def has_change_permission(self, request, obj=None):
        if request.user.is_superuser:
            return True
        if not self.has_module_permission(request):
            return False
        return obj is None or user_can_access_object(request.user, obj)

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))
        if not request.user.is_superuser:
            readonly.extend(["is_superuser", "groups", "user_permissions"])
        return tuple(dict.fromkeys(readonly))

    def save_model(self, request, obj, form, change):
        if not request.user.is_superuser:
            obj.is_superuser = False
        return super().save_model(request, obj, form, change)


@admin.register(Group)
class GroupAdmin(BaseGroupAdmin, ModelAdmin):
    def has_module_permission(self, request):
        return request.user.is_superuser
