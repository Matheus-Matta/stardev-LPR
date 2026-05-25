import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import RequestFactory

from cameras.admin import CameraAdmin
from cameras.models import Camera
from config.admin import UserAdmin
from tenants.admin import UserTenantAccessAdmin
from tenants.models import Business, Tenant, UserProfile, UserTenantAccess


def _request_for(user):
    request = RequestFactory().get("/admin/")
    request.user = user
    return request


@pytest.mark.django_db
def test_staff_admin_sees_only_linked_tenant_data():
    user_model = get_user_model()
    staff = user_model.objects.create_user("staff", password="pass", is_staff=True)
    business = Business.objects.create(name="Administradora")
    tenant_a = Tenant.objects.create(business=business, name="Condominio A", slug="cond-a")
    tenant_b = Tenant.objects.create(business=business, name="Condominio B", slug="cond-b")
    camera_a = Camera.objects.create(name="Camera A", tenant=tenant_a)
    Camera.objects.create(name="Camera B", tenant=tenant_b)
    UserTenantAccess.objects.create(
        user=staff,
        business=business,
        tenant=tenant_a,
        role=UserTenantAccess.Role.OPERATOR,
    )

    model_admin = CameraAdmin(Camera, admin.site)

    assert list(model_admin.get_queryset(_request_for(staff))) == [camera_a]


@pytest.mark.django_db
def test_business_is_admin_profile_sees_all_business_tenants_only():
    user_model = get_user_model()
    business_admin = user_model.objects.create_user(
        "business-admin",
        password="pass",
        is_staff=True,
    )
    business = Business.objects.create(name="Administradora")
    tenant_a = Tenant.objects.create(business=business, name="Condominio A", slug="cond-a")
    tenant_b = Tenant.objects.create(business=business, name="Condominio B", slug="cond-b")
    other_business = Business.objects.create(name="Outra")
    other_tenant = Tenant.objects.create(
        business=other_business,
        name="Condominio C",
        slug="cond-c",
    )
    camera_a = Camera.objects.create(name="Camera A", tenant=tenant_a)
    camera_b = Camera.objects.create(name="Camera B", tenant=tenant_b)
    Camera.objects.create(name="Camera C", tenant=other_tenant)
    UserProfile.objects.create(user=business_admin, business=business, is_admin=True)

    model_admin = CameraAdmin(Camera, admin.site)

    assert set(model_admin.get_queryset(_request_for(business_admin))) == {camera_a, camera_b}


@pytest.mark.django_db
def test_business_admin_user_admin_is_scoped_to_business_users():
    user_model = get_user_model()
    business_admin = user_model.objects.create_user(
        "business-admin",
        password="pass",
        is_staff=True,
    )
    client_user = user_model.objects.create_user("client", password="pass", is_staff=True)
    outside_user = user_model.objects.create_user("outside", password="pass", is_staff=True)
    business = Business.objects.create(name="Administradora")
    tenant = Tenant.objects.create(business=business, name="Condominio A", slug="cond-a")
    UserProfile.objects.create(user=business_admin, business=business, is_admin=True)
    UserTenantAccess.objects.create(
        user=client_user,
        business=business,
        tenant=tenant,
        role=UserTenantAccess.Role.VIEWER,
    )

    model_admin = UserAdmin(user_model, admin.site)
    users = set(model_admin.get_queryset(_request_for(business_admin)))

    assert business_admin in users
    assert client_user in users
    assert outside_user not in users


@pytest.mark.django_db
def test_staff_cannot_change_own_tenant_access_in_admin():
    user_model = get_user_model()
    staff = user_model.objects.create_user("staff", password="pass", is_staff=True)
    business = Business.objects.create(name="Administradora")
    tenant = Tenant.objects.create(business=business, name="Condominio A", slug="cond-a")
    access = UserTenantAccess.objects.create(
        user=staff,
        business=business,
        tenant=tenant,
        role=UserTenantAccess.Role.OPERATOR,
    )

    model_admin = UserTenantAccessAdmin(UserTenantAccess, admin.site)

    assert model_admin.has_view_permission(_request_for(staff), access)
    assert not model_admin.has_change_permission(_request_for(staff), access)
