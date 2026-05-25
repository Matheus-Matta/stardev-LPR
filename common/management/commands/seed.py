"""
Management command: seed

Popula o banco com dados de teste para todas as models do sistema.
Requer que createadminuser ja tenha sido executado.

Uso:
    python manage.py seed
    python manage.py seed --count 5
    python manage.py seed --flush          # limpa dados do tenant antes de criar
    python manage.py seed --tenant principal
"""

import base64
import random
import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from cameras.models import Camera, Gateway
from common.models import (
    AIModelArtifact,
    AuditLog,
    DataProcessingRecord,
    DataSubjectRequest,
    DeadLetterTask,
    SecurityIncident,
    WebhookDelivery,
    WebhookSubscription,
)
from plates.models import AccessEvent, Alert, PlateEvent, PlateRegistry, VehiclePresence
from tenants.models import Business, Tenant

User = get_user_model()

# ── placeholder de imagem ─────────────────────────────────────────────────────
# PNG 1×1 pixel branco — evita depender de arquivos externos
_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAAAAAA6fptV"
    "AAAACklEQVQI12NgAAAAAgAB4iG8MwAAAABJRU5ErkJggg=="
)

# ── dados fake ────────────────────────────────────────────────────────────────
_PLATES = [
    "ABC1234", "DEF5678", "GHI9012", "JKL3456", "MNO7890",
    "PQR1111", "STU2222", "VWX3333", "YZA4444", "BCD5555",
    "ABC1D23", "DEF2E34", "GHI3F45", "JKL4G56", "MNO5H67",
    "PQR6I78", "STU7J89", "VWX8K90", "YZA9L01", "BCD0M12",
]
_NAMES = [
    "Joao Silva", "Maria Santos", "Pedro Costa", "Ana Lima", "Carlos Souza",
    "Fernanda Oliveira", "Lucas Pereira", "Juliana Alves", "Rafael Martins",
    "Beatriz Rocha", "Thiago Fernandes", "Camila Rodrigues",
]
_VEHICLES = ["Gol", "Onix", "HB20", "Polo", "Creta", "Hilux", "Kwid", "Argo", "T-Cross", "Compass"]
_COLORS   = ["Branco", "Prata", "Preto", "Cinza", "Vermelho", "Azul", "Amarelo", "Verde"]
_LOCATIONS = [
    "Portaria Principal", "Entrada Lateral", "Saida Estacionamento",
    "Acesso Garagem", "Cancela Norte", "Cancela Sul",
    "Portao A", "Portao B", "Entrada VIP", "Saida Emergencia",
]


def _pl(i: int) -> str:
    return _PLATES[i % len(_PLATES)]


def _rnd_dt(days_back: int = 30):
    return timezone.now() - timedelta(minutes=random.randint(0, days_back * 1440))


# ── command ───────────────────────────────────────────────────────────────────

class Command(BaseCommand):
    help = "Popula o banco com dados de teste (padrao: 10 registros por model)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--count", type=int, default=10,
            help="Registros por model (padrao: 10)",
        )
        parser.add_argument(
            "--flush", action="store_true",
            help="Remove dados do tenant antes de criar novos",
        )
        parser.add_argument(
            "--tenant", metavar="SLUG", default="",
            help="Slug do tenant alvo (padrao: primeiro ativo)",
        )

    def handle(self, *args, **options):
        count  = options["count"]
        t_slug = options["tenant"]

        business = Business.objects.first()
        if not business:
            raise CommandError("Nenhum Business encontrado. Execute createadminuser primeiro.")

        tenant = (
            Tenant.objects.get(slug=t_slug) if t_slug
            else Tenant.objects.filter(is_active=True).first()
        )
        if not tenant:
            raise CommandError("Nenhum Tenant ativo. Execute createadminuser primeiro.")

        admin = User.objects.filter(is_superuser=True).first()

        if options["flush"]:
            self._flush(tenant)

        self.stdout.write(self.style.HTTP_INFO(
            f"\nSeed  business={business.name}  tenant={tenant.name}  count={count}\n"
            + "-" * 54
        ))

        gateways    = self._seed_gateways(tenant, count)
        cameras     = self._seed_cameras(tenant, gateways, count)
        registries  = self._seed_plate_registries(tenant, admin, count)
        plate_evts  = self._seed_plate_events(tenant, cameras, count)
        access_evts = self._seed_access_events(tenant, cameras, registries, plate_evts, count)
        self._seed_vehicle_presence(tenant, registries, access_evts, count)
        self._seed_alerts(tenant, cameras, gateways, access_evts, count)
        self._seed_audit_logs(tenant, admin, cameras, count)
        subs = self._seed_webhook_subscriptions(tenant, count)
        self._seed_webhook_deliveries(tenant, subs, count)
        self._seed_ai_model_artifacts(tenant, count)
        self._seed_data_processing_records(tenant, count)
        self._seed_data_subject_requests(tenant, count)
        self._seed_security_incidents(tenant, count)
        self._seed_dead_letter_tasks(tenant, count)

        self.stdout.write("-" * 54)
        self.stdout.write(self.style.SUCCESS("Seed concluido."))
        self.stdout.write(f"  Tenant : {tenant.name}")
        self.stdout.write(f"  Acesse : http://localhost:8000/app/\n")

    # ── flush ─────────────────────────────────────────────────────────────────

    def _flush(self, tenant: Tenant) -> None:
        self.stdout.write(self.style.WARNING("Limpando dados anteriores..."))
        Alert.objects.filter(tenant=tenant).delete()
        VehiclePresence.objects.filter(tenant=tenant).delete()
        AccessEvent.objects.filter(tenant=tenant).delete()
        PlateEvent.objects.filter(tenant=tenant).delete()
        PlateRegistry.objects.filter(tenant=tenant).delete()
        Camera.objects.filter(tenant=tenant).delete()
        Gateway.objects.filter(tenant=tenant).delete()
        WebhookDelivery.objects.filter(tenant=tenant).delete()
        WebhookSubscription.objects.filter(tenant=tenant).delete()
        AIModelArtifact.objects.filter(tenant=tenant).delete()
        DataProcessingRecord.objects.filter(tenant=tenant).delete()
        DataSubjectRequest.objects.filter(tenant=tenant).delete()
        SecurityIncident.objects.filter(tenant=tenant).delete()
        DeadLetterTask.objects.filter(tenant=tenant).delete()
        AuditLog.objects.filter(tenant=tenant).delete()
        self.stdout.write(self.style.SUCCESS("  Dados removidos.\n"))

    # ── gateways ──────────────────────────────────────────────────────────────

    def _seed_gateways(self, tenant: Tenant, count: int) -> list:
        statuses = [s.value for s in Gateway.Status]
        result = []
        for i in range(count):
            result.append(Gateway.objects.create(
                name=f"Gateway {i+1:02d} - {_LOCATIONS[i % len(_LOCATIONS)]}",
                tenant=tenant,
                location=_LOCATIONS[i % len(_LOCATIONS)],
                status=statuses[i % len(statuses)],
                last_seen_at=_rnd_dt(7) if i % 3 != 0 else None,
                version=f"1.{i}.0",
                pending_events=random.randint(0, 50),
                cameras_online=random.randint(0, 4),
                cameras_offline=random.randint(0, 2),
                is_active=True,
            ))
        self._ok("Gateway", count)
        return result

    # ── cameras ───────────────────────────────────────────────────────────────

    def _seed_cameras(self, tenant: Tenant, gateways: list, count: int) -> list:
        modes = [m.value for m in Camera.ConnectionMode]
        dirs  = [d.value for d in Camera.DirectionDefault]
        result = []
        for i in range(count):
            mode = modes[i % len(modes)]
            result.append(Camera.objects.create(
                name=f"Camera {i+1:02d} - {_LOCATIONS[i % len(_LOCATIONS)]}",
                tenant=tenant,
                connection_mode=mode,
                direction_default=dirs[i % len(dirs)],
                location=_LOCATIONS[i % len(_LOCATIONS)],
                host=f"192.168.1.{10 + i}",
                port=554,
                rtsp_path=f"/stream/{i+1}",
                timezone="America/Sao_Paulo",
                is_active=True,
                last_seen_at=_rnd_dt(7) if i % 4 != 0 else None,
                gateway=gateways[i % len(gateways)] if mode == "gateway" else None,
            ))
        self._ok("Camera", count)
        return result

    # ── plate registries ──────────────────────────────────────────────────────

    def _seed_plate_registries(self, tenant: Tenant, admin, count: int) -> list:
        list_types  = [PlateRegistry.ListType.WHITELIST, PlateRegistry.ListType.BLACKLIST]
        risk_levels = [r.value for r in PlateRegistry.RiskLevel]
        result = []
        for i in range(count):
            pl = _pl(i)
            lt = list_types[i % 2].value
            obj, _ = PlateRegistry.objects.get_or_create(
                tenant=tenant,
                normalized_plate=pl,
                list_type=lt,
                defaults={
                    "plate": pl,
                    "status": PlateRegistry.Status.ACTIVE,
                    "owner_name": _NAMES[i % len(_NAMES)],
                    "vehicle_model": _VEHICLES[i % len(_VEHICLES)],
                    "vehicle_color": _COLORS[i % len(_COLORS)],
                    "risk_level": risk_levels[i % len(risk_levels)],
                    "block_reason": "Veiculo na lista negra" if lt == "blacklist" else "",
                    "notes": f"Registro de teste #{i+1}",
                    "created_by": admin,
                },
            )
            result.append(obj)
        self._ok("PlateRegistry", count)
        return result

    # ── plate events ──────────────────────────────────────────────────────────

    def _seed_plate_events(self, tenant: Tenant, cameras: list, count: int) -> list:
        statuses  = [PlateEvent.Status.COMPLETED, PlateEvent.Status.PENDING, PlateEvent.Status.ERROR]
        ev_types  = [PlateEvent.EventType.ENTRY, PlateEvent.EventType.EXIT, PlateEvent.EventType.UNKNOWN]
        result = []
        for i in range(count):
            result.append(PlateEvent.objects.create(
                camera=cameras[i % len(cameras)],
                tenant=tenant,
                event_type=ev_types[i % len(ev_types)].value,
                image=ContentFile(_TINY_PNG, name=f"seed_plate_{i+1}.png"),
                captured_at=_rnd_dt(),
                plate_text=_pl(i),
                confidence=round(random.uniform(0.70, 0.99), 4),
                status=statuses[i % len(statuses)].value,
                raw_payload={"source": "seed", "index": i},
            ))
        self._ok("PlateEvent", count)
        return result

    # ── access events ─────────────────────────────────────────────────────────

    def _seed_access_events(
        self, tenant: Tenant, cameras: list, registries: list, plate_evts: list, count: int
    ) -> list:
        decisions   = [d.value for d in AccessEvent.Decision]
        mv_types    = [AccessEvent.MovementType.ENTRY, AccessEvent.MovementType.EXIT,
                       AccessEvent.MovementType.UNKNOWN]
        result = []
        for i in range(count):
            pl  = _pl(i)
            reg = registries[i % len(registries)]
            captured = _rnd_dt()
            result.append(AccessEvent.objects.create(
                tenant=tenant,
                camera=cameras[i % len(cameras)],
                plate_event=plate_evts[i] if i < len(plate_evts) else None,
                plate_registry=reg,
                plate_text=pl,
                normalized_plate=pl,
                list_type_result=reg.list_type,
                decision=decisions[i % len(decisions)],
                decision_reason=f"Decisao de teste #{i+1}",
                movement_type=mv_types[i % len(mv_types)].value,
                confidence=round(random.uniform(0.70, 0.99), 4),
                captured_at=captured,
                status=AccessEvent.Status.PROCESSED,
                processed_at=captured + timedelta(seconds=random.randint(1, 10)),
                raw_payload={"source": "seed"},
            ))
        self._ok("AccessEvent", count)
        return result

    # ── vehicle presence ──────────────────────────────────────────────────────

    def _seed_vehicle_presence(
        self, tenant: Tenant, registries: list, access_evts: list, count: int
    ) -> None:
        statuses = [s.value for s in VehiclePresence.CurrentStatus]
        for i in range(count):
            ev = access_evts[i % len(access_evts)]
            VehiclePresence.objects.get_or_create(
                tenant=tenant,
                normalized_plate=_pl(i),
                defaults={
                    "plate_registry": registries[i % len(registries)],
                    "current_status": statuses[i % len(statuses)],
                    "last_entry_event": ev if ev.movement_type == "entry" else None,
                    "entered_at": _rnd_dt(5),
                    "last_seen_at": _rnd_dt(1),
                    "location": _LOCATIONS[i % len(_LOCATIONS)],
                },
            )
        self._ok("VehiclePresence", count)

    # ── alerts ────────────────────────────────────────────────────────────────

    def _seed_alerts(
        self, tenant: Tenant, cameras: list, gateways: list, access_evts: list, count: int
    ) -> None:
        types      = [a.value for a in Alert.AlertType]
        severities = [s.value for s in Alert.Severity]
        statuses   = [Alert.Status.OPEN.value, Alert.Status.RESOLVED.value]
        for i in range(count):
            atype = types[i % len(types)]
            pl    = _pl(i)
            Alert.objects.create(
                alert_type=atype,
                tenant=tenant,
                access_event=access_evts[i % len(access_evts)],
                plate=pl,
                camera=cameras[i % len(cameras)],
                gateway=gateways[i % len(gateways)] if i % 3 == 0 else None,
                severity=severities[i % len(severities)],
                status=statuses[i % 2],
                message=f"[Seed] {atype} - placa {pl}",
            )
        self._ok("Alert", count)

    # ── audit logs ────────────────────────────────────────────────────────────

    def _seed_audit_logs(self, tenant: Tenant, admin, cameras: list, count: int) -> None:
        actions = [
            "camera.created", "camera.updated", "plate.registered",
            "plate.blocked", "access.reviewed", "user.login",
            "gateway.token_rotated", "plate.deleted", "alert.resolved",
            "webhook.created",
        ]
        for i in range(count):
            cam = cameras[i % len(cameras)]
            AuditLog.objects.create(
                action=actions[i % len(actions)],
                tenant=tenant,
                user=admin,
                ip_address=f"192.168.1.{100 + i}",
                path=f"/api/v1/cameras/{cam.id}/",
                entity_type="Camera",
                entity_id=str(cam.id),
                old_value={"is_active": False},
                new_value={"is_active": True},
                reason=f"Auditoria de teste #{i+1}",
            )
        self._ok("AuditLog", count)

    # ── webhook subscriptions ─────────────────────────────────────────────────

    def _seed_webhook_subscriptions(self, tenant: Tenant, count: int) -> list:
        ev_types = [e.value for e in WebhookSubscription.EventType]
        result = []
        for i in range(count):
            result.append(WebhookSubscription.objects.create(
                url=f"https://hooks.example.com/endpoint-{i+1}",
                tenant=tenant,
                event_type=ev_types[i % len(ev_types)],
                is_active=True,
            ))
        self._ok("WebhookSubscription", count)
        return result

    # ── webhook deliveries ────────────────────────────────────────────────────

    def _seed_webhook_deliveries(self, tenant: Tenant, subs: list, count: int) -> None:
        statuses = [s.value for s in WebhookDelivery.Status]
        for i in range(count):
            sub    = subs[i % len(subs)]
            status = statuses[i % len(statuses)]
            WebhookDelivery.objects.create(
                subscription=sub,
                tenant=tenant,
                event_type=sub.event_type,
                payload={"plate": _pl(i), "source": "seed"},
                status=status,
                response_status_code=200 if status == "success" else None,
                response_body='{"ok": true}' if status == "success" else "",
                attempts=random.randint(1, 3),
                delivered_at=timezone.now() if status == "success" else None,
            )
        self._ok("WebhookDelivery", count)

    # ── AI model artifacts ────────────────────────────────────────────────────

    def _seed_ai_model_artifacts(self, tenant: Tenant, count: int) -> None:
        kinds = [AIModelArtifact.Kind.YOLO.value, AIModelArtifact.Kind.OCR.value]
        for i in range(count):
            kind = kinds[i % 2]
            AIModelArtifact.objects.get_or_create(
                tenant=tenant,
                kind=kind,
                version=f"seed-v{i+1}.0",
                defaults={
                    "storage_uri": f"s3://models/{kind}/seed-v{i+1}.0.pt",
                    "baseline_metrics": {"accuracy": round(random.uniform(0.85, 0.99), 3)},
                    "notes": f"Modelo de teste #{i+1}",
                    "is_active": i == 0,
                },
            )
        self._ok("AIModelArtifact", count)

    # ── data processing records ───────────────────────────────────────────────

    def _seed_data_processing_records(self, tenant: Tenant, count: int) -> None:
        names = [
            "Monitoramento de Acesso Veicular", "Reconhecimento de Placas LPR",
            "Registro de Eventos de Seguranca", "Controle de Estacionamento",
            "Auditoria de Acesso", "Monitoramento de Perimetro",
            "Gestao de Visitantes", "Controle de Frota",
            "Blacklist Veicular", "Relatorios de Seguranca",
        ]
        bases = [
            "Art. 6, I - consentimento",
            "Art. 6, V - execucao de contrato",
            "Art. 6, IX - interesse legitimo",
        ]
        for i in range(count):
            DataProcessingRecord.objects.create(
                name=names[i % len(names)],
                tenant=tenant,
                purpose=f"Tratamento de dados para finalidade de teste #{i+1}",
                legal_basis=bases[i % len(bases)],
                data_categories=["placa_veicular", "imagem", "horario_acesso"],
                retention_days=90,
                owner="DPO - Protecao de Dados",
                is_active=True,
            )
        self._ok("DataProcessingRecord", count)

    # ── data subject requests ─────────────────────────────────────────────────

    def _seed_data_subject_requests(self, tenant: Tenant, count: int) -> None:
        req_types = [r.value for r in DataSubjectRequest.RequestType]
        statuses  = [s.value for s in DataSubjectRequest.Status]
        for i in range(count):
            DataSubjectRequest.objects.create(
                request_type=req_types[i % len(req_types)],
                tenant=tenant,
                requester_name=_NAMES[i % len(_NAMES)],
                requester_contact=f"titular{i+1}@exemplo.com",
                plate_text=_pl(i),
                status=statuses[i % len(statuses)],
                due_at=timezone.now() + timedelta(days=15),
            )
        self._ok("DataSubjectRequest", count)

    # ── security incidents ────────────────────────────────────────────────────

    def _seed_security_incidents(self, tenant: Tenant, count: int) -> None:
        statuses = [s.value for s in SecurityIncident.Status]
        titles = [
            "Acesso nao autorizado detectado",
            "Tentativa de fraude de placa",
            "Falha de autenticacao multipla",
            "Acesso fora de horario permitido",
            "Placa clonada identificada",
            "Incidente de seguranca perimetral",
            "Violacao de politica de acesso",
            "Atividade suspeita no estacionamento",
            "Camera com sinal adulterado",
            "Tentativa de bypass do sistema",
        ]
        for i in range(count):
            SecurityIncident.objects.create(
                title=titles[i % len(titles)],
                tenant=tenant,
                description=f"Descricao detalhada do incidente de seguranca #{i+1}.",
                status=statuses[i % len(statuses)],
                detected_at=_rnd_dt(),
                anpd_due_at=timezone.now() + timedelta(hours=72) if i % 3 == 0 else None,
                affected_data=["placa_veicular", "imagem"],
            )
        self._ok("SecurityIncident", count)

    # ── dead letter tasks ─────────────────────────────────────────────────────

    def _seed_dead_letter_tasks(self, tenant: Tenant, count: int) -> None:
        task_names = [
            "cameras.tasks.capture_camera_frame",
            "plates.tasks.process_plate_event",
            "common.tasks.dispatch_webhook",
            "plates.tasks.update_vehicle_presence",
            "plates.tasks.send_alert",
        ]
        statuses = [s.value for s in DeadLetterTask.Status]
        queues   = ["ocr", "capture", "dead", "reports"]
        for i in range(count):
            DeadLetterTask.objects.create(
                task_name=task_names[i % len(task_names)],
                tenant=tenant,
                task_id=str(uuid.uuid4()),
                queue=queues[i % len(queues)],
                payload={"camera_id": i + 1, "source": "seed"},
                exception_class="RuntimeError",
                exception_message=f"Erro simulado de teste #{i+1}",
                traceback=(
                    f"Traceback (most recent call last):\n"
                    f"  File 'tasks.py', line {10 + i}, in run\n"
                    f"RuntimeError: Erro simulado #{i+1}"
                ),
                retries=random.randint(0, 3),
                status=statuses[i % len(statuses)],
            )
        self._ok("DeadLetterTask", count)

    # ── helper ────────────────────────────────────────────────────────────────

    def _ok(self, label: str, count: int) -> None:
        self.stdout.write(self.style.SUCCESS(f"  [OK] {label:<28} {count} registros"))
