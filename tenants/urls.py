from django.urls import path

from tenants.views import (
    BusinessDetailAPIView,
    BusinessListCreateAPIView,
    GrantTenantAccessAPIView,
    ManagedTenantAccessDetailAPIView,
    ManagedTenantAccessListCreateAPIView,
    MyBusinessListAPIView,
    MyTenantListAPIView,
    TenantDetailAPIView,
    TenantListCreateAPIView,
    UserTenantAccessDetailAPIView,
    UserTenantAccessListCreateAPIView,
)

urlpatterns = [
    path("businesses/", BusinessListCreateAPIView.as_view(), name="business-list"),
    path("businesses/<int:pk>/", BusinessDetailAPIView.as_view(), name="business-detail"),
    path("tenants/", TenantListCreateAPIView.as_view(), name="tenant-list"),
    path("tenants/<int:pk>/", TenantDetailAPIView.as_view(), name="tenant-detail"),
    path("accesses/", UserTenantAccessListCreateAPIView.as_view(), name="tenant-access-list"),
    path(
        "accesses/<int:pk>/",
        UserTenantAccessDetailAPIView.as_view(),
        name="tenant-access-detail",
    ),
    path("my-businesses/", MyBusinessListAPIView.as_view(), name="my-business-list"),
    path("my-tenants/", MyTenantListAPIView.as_view(), name="my-tenant-list"),
    path(
        "managed-accesses/",
        ManagedTenantAccessListCreateAPIView.as_view(),
        name="managed-tenant-access-list",
    ),
    path(
        "managed-accesses/<int:pk>/",
        ManagedTenantAccessDetailAPIView.as_view(),
        name="managed-tenant-access-detail",
    ),
    path("grant-access/", GrantTenantAccessAPIView.as_view(), name="grant-tenant-access"),
]
