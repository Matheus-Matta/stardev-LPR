from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db.models import Q

from tenants.models import Business, Tenant, UserProfile, UserTenantAccess
from tenants.utils import (
    business_ids_administered_by,
    business_ids_visible_for_user,
    first_or_single_visible_tenant,
    is_business_admin,
    tenant_queryset_for_user,
    tenants_visible_for_user,
    user_can_access_object,
    user_ids_visible_for_user,
)


def _is_staff_user(user) -> bool:
    return bool(user and user.is_active and user.is_staff)


def _visible_tenant_ids(user):
    return tenants_visible_for_user(user).values_list("id", flat=True)


def _visible_business_ids(user):
    return business_ids_visible_for_user(user).values_list("id", flat=True)


def _administered_business_ids(user):
    return business_ids_administered_by(user).values_list("id", flat=True)


def scoped_queryset_for_admin(queryset, user):
    model = queryset.model
    if not user or not user.is_authenticated:
        return queryset.none()
    if user.is_superuser:
        return queryset

    if model is Business:
        return queryset.filter(id__in=_visible_business_ids(user)).distinct()
    if model is Tenant:
        return queryset.filter(id__in=_visible_tenant_ids(user)).distinct()
    if model is UserTenantAccess:
        return queryset.filter(
            Q(business_id__in=_administered_business_ids(user)) | Q(user=user),
        ).distinct()
    if model is UserProfile:
        return queryset.filter(
            Q(business_id__in=_administered_business_ids(user)) | Q(user=user),
        ).distinct()
    if model is get_user_model():
        return queryset.filter(id__in=user_ids_visible_for_user(user)).distinct()
    if hasattr(model, "tenant_id"):
        return tenant_queryset_for_user(queryset, user).distinct()
    if hasattr(model, "business_id"):
        return queryset.filter(business_id__in=_visible_business_ids(user)).distinct()
    return queryset.none()


class ScopedForeignKeyMixin:
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        user = request.user
        related_model = db_field.remote_field.model

        if not user.is_superuser:
            if related_model is Tenant or db_field.name == "tenant":
                kwargs["queryset"] = tenants_visible_for_user(user)
            elif related_model is Business or db_field.name == "business":
                if business_ids_administered_by(user).exists():
                    kwargs["queryset"] = business_ids_administered_by(user)
                else:
                    kwargs["queryset"] = business_ids_visible_for_user(user)
            elif related_model is get_user_model():
                kwargs["queryset"] = related_model.objects.filter(
                    id__in=user_ids_visible_for_user(user),
                )
            elif hasattr(related_model, "tenant_id"):
                kwargs["queryset"] = tenant_queryset_for_user(
                    related_model._default_manager.all(),
                    user,
                )
            elif hasattr(related_model, "business_id"):
                kwargs["queryset"] = related_model._default_manager.filter(
                    business_id__in=_visible_business_ids(user),
                )

        return super().formfield_for_foreignkey(db_field, request, **kwargs)


class ScopedInlineMixin(ScopedForeignKeyMixin):
    extra = 0

    def has_view_permission(self, request, obj=None):
        return _is_staff_user(request.user)

    def has_add_permission(self, request, obj=None):
        if not _is_staff_user(request.user):
            return False
        return request.user.is_superuser or business_ids_administered_by(request.user).exists()

    def has_change_permission(self, request, obj=None):
        if not _is_staff_user(request.user):
            return False
        if request.user.is_superuser:
            return True
        return obj is None or user_can_access_object(request.user, obj)

    def has_delete_permission(self, request, obj=None):
        return self.has_change_permission(request, obj)


class TenantScopedAdminMixin(ScopedForeignKeyMixin):
    tenant_field = "tenant"
    business_admin_manage_only = False
    superuser_manage_only = False

    def get_queryset(self, request):
        return scoped_queryset_for_admin(super().get_queryset(request), request.user)

    def has_module_permission(self, request):
        return _is_staff_user(request.user)

    def has_view_permission(self, request, obj=None):
        if not _is_staff_user(request.user):
            return False
        return obj is None or user_can_access_object(request.user, obj)

    def has_add_permission(self, request):
        if not _is_staff_user(request.user):
            return False
        if request.user.is_superuser:
            return True
        if self.superuser_manage_only:
            return False
        if self.business_admin_manage_only:
            return business_ids_administered_by(request.user).exists()
        return tenants_visible_for_user(request.user).exists()

    def has_change_permission(self, request, obj=None):
        if not _is_staff_user(request.user):
            return False
        if request.user.is_superuser:
            return True
        if self.superuser_manage_only:
            return False
        if self.business_admin_manage_only and not business_ids_administered_by(
            request.user,
        ).exists():
            return False
        return obj is None or user_can_access_object(request.user, obj)

    def has_delete_permission(self, request, obj=None):
        if request.user.is_superuser:
            return True
        if self.business_admin_manage_only:
            return self.has_change_permission(request, obj)
        return False

    def get_changeform_initial_data(self, request):
        initial = super().get_changeform_initial_data(request)
        if self.tenant_field not in initial and not request.user.is_superuser:
            tenant = first_or_single_visible_tenant(request.user)
            if tenant:
                initial[self.tenant_field] = tenant.id
        return initial

    def save_model(self, request, obj, form, change):
        if request.user.is_superuser:
            return super().save_model(request, obj, form, change)

        if hasattr(obj, "business_id") and obj.business_id:
            if not business_ids_visible_for_user(request.user).filter(id=obj.business_id).exists():
                raise PermissionDenied("Business not allowed for this user.")

        if hasattr(obj, f"{self.tenant_field}_id"):
            tenant_id = getattr(obj, f"{self.tenant_field}_id", None)
            if not tenant_id:
                tenant = first_or_single_visible_tenant(request.user)
                if not tenant:
                    raise forms.ValidationError(
                        "Select a tenant before saving this object.",
                    )
                setattr(obj, self.tenant_field, tenant)
            elif not tenants_visible_for_user(request.user).filter(id=tenant_id).exists():
                raise PermissionDenied("Tenant not allowed for this user.")

        return super().save_model(request, obj, form, change)


class BusinessAdminAccessMixin(TenantScopedAdminMixin):
    business_admin_manage_only = True

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


class TenantAdminAccessMixin(TenantScopedAdminMixin):
    def has_add_permission(self, request):
        if request.user.is_superuser:
            return True
        return business_ids_administered_by(request.user).exists()

    def has_delete_permission(self, request, obj=None):
        if request.user.is_superuser:
            return True
        return obj is not None and is_business_admin(request.user, obj.business_id)


class UserAccessAdminMixin(TenantScopedAdminMixin):
    business_admin_manage_only = True

    def has_add_permission(self, request):
        if self.superuser_manage_only:
            return request.user.is_superuser
        return request.user.is_superuser or business_ids_administered_by(request.user).exists()

    def has_view_permission(self, request, obj=None):
        if not _is_staff_user(request.user):
            return False
        return obj is None or user_can_access_object(request.user, obj)

    def has_change_permission(self, request, obj=None):
        if request.user.is_superuser:
            return True
        if not _is_staff_user(request.user):
            return False
        if self.superuser_manage_only:
            return False
        if not business_ids_administered_by(request.user).exists():
            return False
        return obj is None or user_can_access_object(request.user, obj)
