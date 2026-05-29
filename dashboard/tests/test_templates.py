"""
Testes de renderização de templates.

Verifica que cada página do dashboard renderiza sem erros (HTTP 500),
cobrindo todos os templates em templates/app/*.html.

Estratégia:
  - setUpTestData cria os objetos mínimos necessários (usuário, câmera, evento, etc.)
  - setUp faz force_login para bypassar autenticação
  - Cada teste faz GET na URL e garante que não retorna 500
  - Erros de template (TemplateSyntaxError, AttributeError, tag inválida, variável
    faltando que causaria exceção) sempre resultam em HTTP 500 no Django
"""

import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

User = get_user_model()


class TemplateRenderTests(TestCase):
    """
    Testa a renderização de todos os templates do dashboard.

    Um status 200 confirma que o template renderizou sem erro.
    Um status 302 indica redirecionamento (aceitável — não é falha de template).
    Um status 500 indica erro de template ou de view e falha o teste.
    """

    @classmethod
    def setUpTestData(cls):
        from cameras.models import Camera, Gateway
        from plates.models import AccessEvent, Alert, PlateRegistry
        from tenants.models import Business, Tenant

        # ── Usuário ───────────────────────────────────────────────────────────
        cls.user = User.objects.create_superuser(
            username="test_admin",
            email="test@lpr.test",
            password="testpass123",
        )

        # ── Estrutura de tenant ────────────────────────────────────────────────
        cls.business = Business.objects.create(name="Empresa Teste")
        cls.tenant = Tenant.objects.create(
            business=cls.business,
            name="Unidade Teste",
            slug="unidade-teste",
        )

        # ── Câmera e gateway ──────────────────────────────────────────────────
        cls.camera = Camera.objects.create(name="Camera Teste")
        cls.gateway = Gateway.objects.create(name="Gateway Teste")

        # ── Placa registrada ──────────────────────────────────────────────────
        cls.plate = PlateRegistry.objects.create(
            plate="ABC1234",
            normalized_plate="ABC1234",
            list_type="unknown",
        )

        # ── Evento de acesso ──────────────────────────────────────────────────
        cls.event = AccessEvent.objects.create(
            event_uuid=uuid.uuid4(),
            camera=cls.camera,
        )

        # ── Alerta ────────────────────────────────────────────────────────────
        cls.alert = Alert.objects.create(
            alert_type="unknown_plate_detected",
            message="Placa desconhecida detectada.",
            access_event=cls.event,
        )

    def setUp(self):
        self.client.force_login(self.user)

    # ── helper ─────────────────────────────────────────────────────────────────

    def assertRenders(self, url, msg=None):
        """GET na URL não deve retornar 500. Aceita 200 ou 302."""
        response = self.client.get(url, follow=False)
        self.assertNotEqual(
            response.status_code,
            500,
            msg or f"Template retornou 500 em: {url}",
        )
        return response

    # ── Autenticação ───────────────────────────────────────────────────────────

    def test_login_page(self):
        self.client.logout()
        r = self.assertRenders(reverse("lpr:login"))
        self.assertEqual(r.status_code, 200)

    # ── Páginas principais ────────────────────────────────────────────────────

    def test_dashboard(self):
        self.assertRenders(reverse("lpr:dashboard"))

    def test_events(self):
        self.assertRenders(reverse("lpr:events"))

    def test_cameras(self):
        self.assertRenders(reverse("lpr:cameras"))

    def test_gateways(self):
        self.assertRenders(reverse("lpr:gateways"))

    def test_alerts(self):
        self.assertRenders(reverse("lpr:alerts"))

    def test_presence(self):
        self.assertRenders(reverse("lpr:presence"))

    def test_plates(self):
        self.assertRenders(reverse("lpr:plates"))

    def test_plate_search(self):
        self.assertRenders(reverse("lpr:plate-search"))

    def test_plate_search_with_query(self):
        self.assertRenders(reverse("lpr:plate-search") + "?q=ABC1234")

    def test_plates_import(self):
        self.assertRenders(reverse("lpr:plates-import"))

    # ── Detalhes (requerem pk) ─────────────────────────────────────────────────

    def test_event_detail(self):
        self.assertRenders(reverse("lpr:event-detail", args=[self.event.pk]))

    def test_event_correct(self):
        self.assertRenders(reverse("lpr:event-correct", args=[self.event.pk]))

    def test_event_review(self):
        self.assertRenders(reverse("lpr:event-review", args=[self.event.pk]))

    def test_plate_detail(self):
        self.assertRenders(reverse("lpr:plate-detail", args=[self.plate.pk]))

    # ── Câmera: CRUD + live ────────────────────────────────────────────────────

    def test_camera_create(self):
        self.assertRenders(reverse("lpr:camera-create"))

    def test_camera_edit(self):
        self.assertRenders(reverse("lpr:camera-edit", args=[self.camera.pk]))

    def test_camera_live(self):
        self.assertRenders(reverse("lpr:camera-live", args=[self.camera.pk]))

    # ── Gateway: CRUD ──────────────────────────────────────────────────────────

    def test_gateway_create(self):
        self.assertRenders(reverse("lpr:gateway-create"))

    def test_gateway_edit(self):
        self.assertRenders(reverse("lpr:gateway-edit", args=[self.gateway.pk]))

    # ── Placas: CRUD ──────────────────────────────────────────────────────────

    def test_plate_create(self):
        self.assertRenders(reverse("lpr:plate-create"))

    # ── Tenancy ────────────────────────────────────────────────────────────────

    def test_tenant_switch(self):
        self.assertRenders(reverse("lpr:tenant-switch"))

    def test_companies(self):
        self.assertRenders(reverse("lpr:companies"))

    def test_company_create(self):
        self.assertRenders(reverse("lpr:company-create"))

    def test_company_edit(self):
        self.assertRenders(reverse("lpr:company-edit", args=[self.business.pk]))

    def test_tenants(self):
        self.assertRenders(reverse("lpr:tenants"))

    def test_tenant_create(self):
        self.assertRenders(reverse("lpr:tenant-create"))

    def test_tenant_edit(self):
        self.assertRenders(reverse("lpr:tenant-edit", args=[self.tenant.pk]))

    def test_users(self):
        self.assertRenders(reverse("lpr:users"))

    def test_user_create(self):
        self.assertRenders(reverse("lpr:user-create"))

    def test_user_edit(self):
        self.assertRenders(reverse("lpr:user-edit", args=[self.user.pk]))

    # ── Plataforma ─────────────────────────────────────────────────────────────

    def test_webhooks(self):
        self.assertRenders(reverse("lpr:webhooks"))

    def test_webhook_create(self):
        self.assertRenders(reverse("lpr:webhook-create"))

    def test_audit(self):
        self.assertRenders(reverse("lpr:audit"))

    def test_lgpd(self):
        self.assertRenders(reverse("lpr:lgpd"))

    def test_settings(self):
        self.assertRenders(reverse("lpr:settings"))

    # ── Perfil ─────────────────────────────────────────────────────────────────

    def test_profile(self):
        self.assertRenders(reverse("lpr:profile"))

    # ── Página de filtros com parâmetros (cobre branches condicionais) ─────────

    def test_events_with_filters(self):
        self.assertRenders(
            reverse("lpr:events") + "?q_plate=ABC1234&q_decision=allowed"
        )

    def test_cameras_with_filters(self):
        self.assertRenders(reverse("lpr:cameras") + "?q=teste&q_status=online")

    def test_alerts_with_filters(self):
        self.assertRenders(reverse("lpr:alerts") + "?q_status=open&q_severity=critical")

    def test_plates_with_filters(self):
        self.assertRenders(reverse("lpr:plates") + "?q_plate=ABC&q_status=blacklist")

    # ── APIs JSON (não devem retornar 500) ─────────────────────────────────────

    def test_api_live_status(self):
        r = self.assertRenders(reverse("lpr:api-live-status"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"].split(";")[0], "application/json")

    def test_api_events_poll(self):
        r = self.assertRenders(reverse("lpr:api-events-poll"))
        self.assertEqual(r.status_code, 200)

    def test_api_camera_events(self):
        r = self.assertRenders(
            reverse("lpr:api-camera-events", args=[self.camera.pk])
        )
        self.assertEqual(r.status_code, 200)

    # ── Acesso não autenticado redireciona (não expõe 500) ─────────────────────

    def test_unauthenticated_redirects(self):
        self.client.logout()
        urls = [
            reverse("lpr:dashboard"),
            reverse("lpr:events"),
            reverse("lpr:cameras"),
            reverse("lpr:camera-live", args=[self.camera.pk]),
        ]
        for url in urls:
            with self.subTest(url=url):
                r = self.client.get(url)
                self.assertIn(
                    r.status_code,
                    [302, 403],
                    f"URL protegida deveria redirecionar: {url}",
                )
