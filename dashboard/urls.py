from django.urls import path

from . import views

app_name = "lpr"

urlpatterns = [
    # Operação principal
    path("", views.DashboardView.as_view(), name="dashboard"),
    path("events/", views.EventsView.as_view(), name="events"),
    path("cameras/", views.CamerasView.as_view(), name="cameras"),
    path("gateways/", views.GatewaysView.as_view(), name="gateways"),
    path("alerts/", views.AlertsView.as_view(), name="alerts"),
    path("presence/", views.StubView.as_view(page_title="Presença de Veículos", active_module="presence"), name="presence"),
    path("plates/", views.PlatesView.as_view(), name="plates"),

    # Ações em registros
    path("plates/import/", views.StubView.as_view(page_title="Importar Placas CSV", active_module="whitelist"), name="plates-import"),
    path("plates/<int:pk>/", views.StubView.as_view(page_title="Editar Placa", active_module="whitelist"), name="plate-detail"),
    path("events/<int:pk>/", views.StubView.as_view(page_title="Detalhe do Evento", active_module="events"), name="event-detail"),
    path("events/<int:pk>/correct/", views.StubView.as_view(page_title="Corrigir Placa", active_module="events"), name="event-correct"),
    path("events/<int:pk>/review/", views.StubView.as_view(page_title="Revisar Evento", active_module="events"), name="event-review"),
    path("alerts/<int:pk>/treat/", views.AlertActionView.as_view(), name="alert-treat"),
    path("alerts/<int:pk>/resolve/", views.AlertActionView.as_view(), name="alert-resolve"),
    path("export/", views.StubView.as_view(page_title="Exportar Dados", active_module="dashboard"), name="export"),
    path("plate-search/", views.PlateSearchView.as_view(), name="plate-search"),

    # Cadastros (tenancy)
    path("tenant/switch/", views.StubView.as_view(page_title="Alterar Unidade", active_module="tenants"), name="tenant-switch"),
    path("companies/", views.StubView.as_view(page_title="Empresas", active_module="companies"), name="companies"),
    path("tenants/", views.StubView.as_view(page_title="Tenants / Unidades", active_module="tenants"), name="tenants"),
    path("users/", views.StubView.as_view(page_title="Usuários", active_module="users"), name="users"),

    # Plataforma
    path("webhooks/", views.StubView.as_view(page_title="Webhooks", active_module="webhooks"), name="webhooks"),
    path("audit/", views.StubView.as_view(page_title="Auditoria", active_module="audit"), name="audit"),
    path("lgpd/", views.StubView.as_view(page_title="LGPD & Privacidade", active_module="lgpd"), name="lgpd"),
    path("settings/", views.StubView.as_view(page_title="Configurações", active_module="settings"), name="settings"),
]
