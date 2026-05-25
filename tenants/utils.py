from django.db.models import Q

from tenants.models import Business, Tenant, UserTenantAccess

BUSINESS_ADMIN_ROLES = {UserTenantAccess.Role.OWNER, UserTenantAccess.Role.ADMIN}


def business_admin_profile(user):
    if not user or not user.is_authenticated:
        return None
    profile = getattr(user, "tenant_profile", None)
    if profile and profile.is_admin and profile.business_id:
        return profile
    return None


def business_ids_administered_by(user):
    if not user or not user.is_authenticated:
        return Business.objects.none()
    if user.is_superuser:
        return Business.objects.filter(is_active=True)

    access_business_ids = UserTenantAccess.objects.filter(
        user=user,
        tenant__isnull=True,
        role__in=BUSINESS_ADMIN_ROLES,
        is_active=True,
    ).values_list("business_id", flat=True)
    query = Q(id__in=access_business_ids)

    profile = business_admin_profile(user)
    if profile:
        query |= Q(id=profile.business_id)

    return Business.objects.filter(query, is_active=True).distinct()


def business_ids_visible_for_user(user):
    if not user or not user.is_authenticated:
        return Business.objects.none()
    if user.is_superuser:
        return Business.objects.filter(is_active=True)

    admin_businesses = business_ids_administered_by(user).values_list("id", flat=True)
    tenant_businesses = UserTenantAccess.objects.filter(
        user=user,
        tenant__isnull=False,
        is_active=True,
    ).values_list("business_id", flat=True)
    return Business.objects.filter(
        Q(id__in=admin_businesses) | Q(id__in=tenant_businesses),
        is_active=True,
    ).distinct()


def user_ids_visible_for_user(user):
    if not user or not user.is_authenticated:
        return []
    user_model = user.__class__
    if user.is_superuser:
        return user_model.objects.values_list("id", flat=True)

    administered_businesses = business_ids_administered_by(user)
    if administered_businesses.exists():
        return (
            user_model.objects.filter(
                Q(id=user.id)
                | Q(tenant_accesses__business__in=administered_businesses)
                | Q(tenant_profile__business__in=administered_businesses)
            )
            .distinct()
            .values_list("id", flat=True)
        )
    return user_model.objects.filter(id=user.id).values_list("id", flat=True)


def is_business_admin(user, business_id: int) -> bool:
    if not user or not user.is_authenticated or not business_id:
        return False
    if user.is_superuser:
        return True

    profile = business_admin_profile(user)
    if profile and profile.business_id == business_id:
        return True

    return UserTenantAccess.objects.filter(
        user=user,
        business_id=business_id,
        tenant__isnull=True,
        role__in=BUSINESS_ADMIN_ROLES,
        is_active=True,
    ).exists()


def tenants_visible_for_user(user):
    if not user or not user.is_authenticated:
        return Tenant.objects.none()
    if user.is_superuser:
        return Tenant.objects.filter(is_active=True)

    profile = business_admin_profile(user)
    direct_tenant_ids = UserTenantAccess.objects.filter(
        user=user,
        tenant__isnull=False,
        is_active=True,
    ).values_list("tenant_id", flat=True)
    business_ids = UserTenantAccess.objects.filter(
        user=user,
        tenant__isnull=True,
        is_active=True,
    ).values_list("business_id", flat=True)

    query = Q(id__in=direct_tenant_ids) | Q(business_id__in=business_ids)
    if profile:
        query |= Q(business_id=profile.business_id)

    return Tenant.objects.filter(query, is_active=True).distinct()


def get_request_tenant(request) -> Tenant | None:
    tenant_id = request.headers.get("X-Tenant-ID") or request.query_params.get("tenant_id")
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return None

    queryset = Tenant.objects.filter(is_active=True)
    if tenant_id:
        queryset = queryset.filter(id=tenant_id)

    if user.is_superuser:
        return queryset.first()

    return (queryset & tenants_visible_for_user(user)).first()


def tenant_queryset_for_user(queryset, user, tenant_id=None):
    if not hasattr(queryset.model, "tenant_id"):
        return queryset
    if not user or not user.is_authenticated:
        return queryset.none()
    if user.is_superuser:
        return queryset.filter(tenant_id=tenant_id) if tenant_id else queryset

    allowed_tenant_ids = tenants_visible_for_user(user).values_list("id", flat=True)
    if tenant_id:
        allowed_tenant_ids = tenants_visible_for_user(user).filter(id=tenant_id).values_list(
            "id",
            flat=True,
        )
    return queryset.filter(tenant_id__in=allowed_tenant_ids)


def user_can_access_tenant(user, tenant_id) -> bool:
    if not user or not user.is_authenticated or not tenant_id:
        return False
    if user.is_superuser:
        return True
    return tenants_visible_for_user(user).filter(id=tenant_id).exists()


def user_can_access_business(user, business_id) -> bool:
    if not user or not user.is_authenticated or not business_id:
        return False
    if user.is_superuser:
        return True
    return business_ids_visible_for_user(user).filter(id=business_id).exists()


def user_can_access_object(user, obj) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if isinstance(obj, Business):
        return user_can_access_business(user, obj.id)
    if isinstance(obj, Tenant):
        return user_can_access_tenant(user, obj.id)
    if isinstance(obj, UserTenantAccess):
        if is_business_admin(user, obj.business_id):
            return True
        return obj.user_id == user.id and (
            obj.tenant_id is None or user_can_access_tenant(user, obj.tenant_id)
        )
    if hasattr(obj, "_meta") and obj._meta.label == "tenants.UserProfile":
        if obj.business_id and is_business_admin(user, obj.business_id):
            return True
        return obj.user_id == user.id
    if hasattr(obj, "tenant_id"):
        return user_can_access_tenant(user, obj.tenant_id)
    if hasattr(obj, "business_id"):
        return user_can_access_business(user, obj.business_id)
    if obj.__class__ is user.__class__:
        return obj.id in set(user_ids_visible_for_user(user))
    return False


def validate_tenant_for_user(user, tenant):
    if tenant and not user_can_access_tenant(user, tenant.id):
        from rest_framework import serializers

        raise serializers.ValidationError({"tenant": "Tenant not allowed for this user."})
    return tenant


def validate_related_tenant_for_user(user, obj, field_name):
    related = getattr(obj, field_name, None)
    if related and hasattr(related, "tenant_id") and not user_can_access_tenant(
        user,
        related.tenant_id,
    ):
        from rest_framework import serializers

        raise serializers.ValidationError({field_name: "Object not allowed for this tenant."})
    return related


def first_or_single_visible_tenant(user):
    tenants = tenants_visible_for_user(user)
    first = tenants.first()
    if first and tenants.count() == 1:
        return first
    return None


def business_admin_accesses(user):
    return UserTenantAccess.objects.filter(
        user=user,
        tenant__isnull=True,
        role__in=BUSINESS_ADMIN_ROLES,
        is_active=True,
    )


def tenant_accesses(user):
    return UserTenantAccess.objects.filter(user=user, tenant__isnull=False, is_active=True)
