from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from common.views import HealthCheckView, TokenLogoutView
from plates.views import AccessEventDashboardView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("app/", include("dashboard.urls")),
    path("health/", HealthCheckView.as_view(), name="health"),
    path(
        "dashboard/access-events/",
        AccessEventDashboardView.as_view(),
        name="access-event-dashboard",
    ),
    path("api/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/token/logout/", TokenLogoutView.as_view(), name="token_logout"),
    path("api/ops/", include("common.urls")),
    path("api/tenancy/", include("tenants.urls")),
    path("api/cameras/", include("cameras.urls")),
    path("api/plates/", include("plates.urls")),
    path("api/v1/ingest/", include("ingest.urls")),
    path("api/v1/tenancy/", include("tenants.urls")),
    path("api/v1/cameras/", include("cameras.urls")),
    path("api/v1/gateways/", include("cameras.gateway_urls")),
    path("api/v1/plates/", include("plates.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
