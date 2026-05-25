import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APIClient

from tenants.models import Business, Tenant, UserTenantAccess


@pytest.mark.django_db
@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
def test_business_admin_lists_all_tenants_in_their_business():
    user_model = get_user_model()
    admin = user_model.objects.create_user("business-admin", password="pass")
    business = Business.objects.create(name="Administradora")
    tenant_a = Tenant.objects.create(business=business, name="Condominio A", slug="cond-a")
    tenant_b = Tenant.objects.create(business=business, name="Condominio B", slug="cond-b")
    other_business = Business.objects.create(name="Outra")
    Tenant.objects.create(business=other_business, name="Condominio C", slug="cond-c")
    UserTenantAccess.objects.create(
        user=admin,
        business=business,
        role=UserTenantAccess.Role.ADMIN,
    )
    client = APIClient()
    client.force_authenticate(admin)

    response = client.get("/api/v1/tenancy/my-tenants/")

    assert response.status_code == 200
    returned_ids = {item["id"] for item in response.json()}
    assert returned_ids == {tenant_a.id, tenant_b.id}


@pytest.mark.django_db
@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
def test_business_admin_grants_access_to_specific_tenant():
    user_model = get_user_model()
    admin = user_model.objects.create_user("business-admin", password="pass")
    business = Business.objects.create(name="Administradora")
    tenant = Tenant.objects.create(business=business, name="Condominio A", slug="cond-a")
    UserTenantAccess.objects.create(
        user=admin,
        business=business,
        role=UserTenantAccess.Role.ADMIN,
    )
    client = APIClient()
    client.force_authenticate(admin)

    response = client.post(
        "/api/v1/tenancy/grant-access/",
        {
            "business": business.id,
            "tenant": tenant.id,
            "role": "viewer",
            "email": "cliente@example.com",
        },
        format="json",
    )

    assert response.status_code == 201
    created_user = user_model.objects.get(email="cliente@example.com")
    assert UserTenantAccess.objects.filter(
        user=created_user,
        business=business,
        tenant=tenant,
        role=UserTenantAccess.Role.VIEWER,
    ).exists()
    assert response.json()["generated_password"]
