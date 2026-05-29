from django.urls import path

from . import views

app_name = "lpr"

urlpatterns = [
    # Autenticação do app
    path("login/", views.AppLoginView.as_view(), name="login"),
    path("logout/", views.AppLogoutView.as_view(), name="logout"),

    # Operação principal
    path("", views.DashboardView.as_view(), name="dashboard"),
    path("events/", views.EventsView.as_view(), name="events"),
    path("cameras/", views.CamerasView.as_view(), name="cameras"),
    path("gateways/", views.GatewaysView.as_view(), name="gateways"),
    path("alerts/", views.AlertsView.as_view(), name="alerts"),
    path("presence/", views.PresenceView.as_view(), name="presence"),
    path("plates/", views.PlatesView.as_view(), name="plates"),

    # Ações em registros
    path("plates/import/", views.PlateImportView.as_view(), name="plates-import"),
    path("plates/<int:pk>/", views.PlateDetailView.as_view(), name="plate-detail"),
    path("events/<int:pk>/", views.EventDetailView.as_view(), name="event-detail"),
    path("events/<int:pk>/correct/", views.EventCorrectView.as_view(), name="event-correct"),
    path("events/<int:pk>/review/", views.EventReviewView.as_view(), name="event-review"),
    path("events/<int:pk>/register/", views.EventQuickRegisterView.as_view(), name="event-register"),
    path("alerts/<int:pk>/treat/", views.AlertActionView.as_view(), name="alert-treat"),
    path("alerts/<int:pk>/resolve/", views.AlertActionView.as_view(), name="alert-resolve"),
    path("export/", views.StubView.as_view(page_title="Exportar Dados", active_module="dashboard"), name="export"),
    path("plate-search/", views.PlateSearchView.as_view(), name="plate-search"),

    # Câmeras CRUD
    path("cameras/create/", views.CameraCreateView.as_view(), name="camera-create"),
    path("cameras/<int:pk>/edit/", views.CameraEditView.as_view(), name="camera-edit"),
    path("cameras/<int:pk>/live/", views.CameraLiveView.as_view(), name="camera-live"),

    # Gateways CRUD
    path("gateways/create/", views.GatewayCreateView.as_view(), name="gateway-create"),
    path("gateways/<int:pk>/edit/", views.GatewayEditView.as_view(), name="gateway-edit"),

    # Placas CRUD
    path("plates/create/", views.PlateCreateView.as_view(), name="plate-create"),

    # Cadastros (tenancy)
    path("tenant/switch/", views.TenantSwitchView.as_view(), name="tenant-switch"),
    path("companies/", views.CompaniesView.as_view(), name="companies"),
    path("companies/create/", views.CompanyCreateView.as_view(), name="company-create"),
    path("companies/<int:pk>/edit/", views.CompanyEditView.as_view(), name="company-edit"),
    path("tenants/", views.TenantsView.as_view(), name="tenants"),
    path("tenants/create/", views.TenantCreateView.as_view(), name="tenant-create"),
    path("tenants/<int:pk>/edit/", views.TenantEditView.as_view(), name="tenant-edit"),
    path("users/", views.UsersView.as_view(), name="users"),
    path("users/create/", views.UserCreateView.as_view(), name="user-create"),
    path("users/<int:pk>/edit/", views.UserEditView.as_view(), name="user-edit"),

    # Plataforma
    path("webhooks/", views.WebhooksView.as_view(), name="webhooks"),
    path("webhooks/create/", views.WebhookCreateView.as_view(), name="webhook-create"),
    path("webhooks/<int:pk>/edit/", views.WebhookEditView.as_view(), name="webhook-edit"),
    path("audit/", views.AuditView.as_view(), name="audit"),
    path("lgpd/", views.LGPDView.as_view(), name="lgpd"),
    path("settings/", views.SettingsView.as_view(), name="settings"),

    # Perfil
    path("profile/", views.ProfileEditView.as_view(), name="profile"),

    # APIs de polling (JSON) — usadas pelo frontend em tempo real
    path("api/live-status/",                    views.LiveStatusAPIView.as_view(),       name="api-live-status"),
    path("api/events/poll/",                    views.LiveEventsAPIView.as_view(),       name="api-events-poll"),
    path("api/cameras/<int:pk>/events/",        views.LiveCameraEventsAPIView.as_view(), name="api-camera-events"),
]
