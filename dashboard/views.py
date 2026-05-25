from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.timesince import timesince
from django.views.generic import TemplateView, View

from cameras.models import Camera, Gateway
from plates.models import AccessEvent, Alert, PlateRegistry


# ---------------------------------------------------------------------------
# View-layer adapter dataclasses
# ---------------------------------------------------------------------------

@dataclass
class KpiData:
    events_total: int
    entries: int
    exits: int
    allowed: int
    blocked: int
    unknown: int


@dataclass
class CameraRow:
    name: str
    code: str
    state: str
    connection_mode_display: str
    model_label: str
    fps: Any
    last_read_human: str


@dataclass
class GatewayRow:
    code: str
    state: str
    mode_display: str
    cameras_count: int
    cpu_pct: int
    queue_size: int
    last_seen_human: str


@dataclass
class EventRow:
    id: int
    short_id: str
    plate: str
    snapshot: Any
    direction: str
    camera_name: str
    tenant_name: str
    confidence: float
    confidence_pct: int
    classification: str
    decision_kind: str
    created_at: Any

    def get_classification_display(self) -> str:
        return {
            "whitelist": "Whitelist",
            "blacklist": "Blacklist",
            "unknown": "Desconhecida",
            "temporary": "Temporária",
        }.get(self.classification, self.classification.capitalize())


@dataclass
class AlertRow:
    id: int
    severity: str
    title: str
    meta: str
    created_at_human: str
    icon: str

    def get_severity_display(self) -> str:
        return {"critical": "Crítico", "warning": "Atenção", "info": "Info"}.get(
            self.severity, self.severity
        )


@dataclass
class PlateRow:
    id: int
    plate: str
    owner_label: str
    vehicle_label: str
    validity_label: str
    list_kind: str
    last_event_label: str

    def get_status_display(self) -> str:
        return {
            "whitelist": "Whitelist",
            "blacklist": "Blacklist",
            "unknown": "Desconhecida",
            "temporary": "Temporária",
        }.get(self.list_kind, self.list_kind.capitalize())


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

_ALERT_TITLES = {
    "blacklist_detected": "Placa bloqueada detectada",
    "unknown_plate_detected": "Placa desconhecida detectada",
    "manual_review_required": "Revisão manual solicitada",
    "gateway_offline": "Gateway offline",
    "camera_offline": "Câmera offline",
    "duplicate_entry": "Entrada duplicada detectada",
    "exit_without_entry": "Saída sem entrada correspondente",
}

_ALERT_ICONS = {
    "blacklist_detected": "block",
    "camera_offline": "cam",
    "gateway_offline": "queue",
    "manual_review_required": "eye",
}

_DECISION_KIND = {
    "allowed": "allow",
    "blocked": "block",
    "unknown": "unknown",
    "manual_review": "review",
    "error": "error",
}


def _human_time(dt) -> str:
    if dt is None:
        return "—"
    return timesince(dt, timezone.now()) + " atrás"


def _camera_state(cam: Camera) -> str:
    if not cam.is_active:
        return "offline"
    if cam.last_seen_at is None:
        return "offline"
    now = timezone.now()
    if cam.last_seen_at >= now - datetime.timedelta(minutes=5):
        return "online"
    if cam.last_seen_at >= now - datetime.timedelta(minutes=30):
        return "degraded"
    return "offline"


def _build_camera_row(cam: Camera) -> CameraRow:
    return CameraRow(
        name=cam.name,
        code=cam.camera_key or "—",
        state=_camera_state(cam),
        connection_mode_display=cam.get_connection_mode_display(),
        model_label=cam.location or "",
        fps=None,
        last_read_human=_human_time(cam.last_seen_at),
    )


def _build_gateway_row(gw: Gateway) -> GatewayRow:
    state_map = {
        Gateway.Status.ONLINE: "online",
        Gateway.Status.OFFLINE: "offline",
        Gateway.Status.UNKNOWN: "inactive",
    }
    state = state_map.get(gw.status, "inactive")
    if state == "online" and gw.pending_events > 5:
        state = "queue"
    return GatewayRow(
        code=gw.name,
        state=state,
        mode_display="Push HTTP",
        cameras_count=gw.cameras.count(),
        cpu_pct=0,
        queue_size=gw.pending_events,
        last_seen_human=_human_time(gw.last_seen_at),
    )


def _build_event_row(ev: AccessEvent) -> EventRow:
    plate = ev.normalized_plate or ev.plate_text or "—"
    # Use the pre-resolved list_type_result or fallback to the FK
    if ev.list_type_result:
        classification = ev.list_type_result
    elif ev.plate_registry:
        classification = ev.plate_registry.list_type
    else:
        classification = "unknown"
    confidence = float(ev.confidence) if ev.confidence else 0.0
    direction = "in" if ev.movement_type == AccessEvent.MovementType.ENTRY else "out"
    snapshot = ev.crop_image if ev.crop_image else (ev.image if ev.image else None)
    short_id = str(ev.event_uuid)[:8] if ev.event_uuid else str(ev.id)
    return EventRow(
        id=ev.id,
        short_id=short_id,
        plate=plate,
        snapshot=snapshot,
        direction=direction,
        camera_name=ev.camera.name if ev.camera else "—",
        tenant_name=(ev.camera.tenant.name if ev.camera and ev.camera.tenant else "—"),
        confidence=confidence,
        confidence_pct=int(confidence * 100),
        classification=classification,
        decision_kind=_DECISION_KIND.get(ev.decision, "unknown"),
        created_at=ev.captured_at,
    )


def _build_alert_row(alert: Alert) -> AlertRow:
    title = _ALERT_TITLES.get(alert.alert_type, alert.get_alert_type_display())
    icon = _ALERT_ICONS.get(alert.alert_type, "help")
    meta = ""
    if alert.access_event:
        meta = alert.access_event.normalized_plate or ""
    return AlertRow(
        id=alert.id,
        severity=alert.severity,
        title=title,
        meta=meta,
        created_at_human=_human_time(alert.created_at),
        icon=icon,
    )


def _build_plate_row(p: PlateRegistry) -> PlateRow:
    vehicle_parts = [p.vehicle_model, p.vehicle_color]
    vehicle_label = " · ".join(v for v in vehicle_parts if v) or "—"
    if p.valid_until:
        validity_label = p.valid_until.strftime("%d/%m/%Y")
    elif p.valid_from:
        validity_label = f"A partir de {p.valid_from.strftime('%d/%m/%Y')}"
    else:
        validity_label = "Sem validade"
    return PlateRow(
        id=p.id,
        plate=p.plate or p.normalized_plate,
        owner_label=p.owner_name or "—",
        vehicle_label=vehicle_label,
        validity_label=validity_label,
        list_kind=p.list_type,
        last_event_label="—",
    )


# ---------------------------------------------------------------------------
# Base mixin
# ---------------------------------------------------------------------------

class DashboardMixin(LoginRequiredMixin):
    login_url = "/admin/login/"
    active_module: str = "dashboard"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.setdefault("active_module", self.active_module)
        ctx.setdefault("app_version", "4.12.0")
        ctx.setdefault("build_id", "2026.05.24")
        ctx.setdefault("environment", "development" if settings.DEBUG else "production")
        ctx.setdefault("notifications_unread", 0)
        ctx.setdefault("event_count", 0)
        try:
            ctx.setdefault(
                "alert_count",
                Alert.objects.filter(status=Alert.Status.OPEN).count(),
            )
        except Exception:
            ctx.setdefault("alert_count", 0)
        return ctx


# ---------------------------------------------------------------------------
# Stub / placeholder view
# ---------------------------------------------------------------------------

class StubView(DashboardMixin, TemplateView):
    template_name = "app/stub.html"
    page_title: str = "Página em desenvolvimento"
    active_module: str = "dashboard"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = self.page_title
        ctx["active_module"] = self.active_module
        return ctx


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

class DashboardView(DashboardMixin, TemplateView):
    template_name = "app/dashboard.html"
    active_module = "dashboard"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        now = timezone.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        # KPI
        qs_today = AccessEvent.objects.filter(captured_at__gte=today_start)
        ctx["kpi"] = KpiData(
            events_total=qs_today.count(),
            entries=qs_today.filter(movement_type=AccessEvent.MovementType.ENTRY).count(),
            exits=qs_today.filter(movement_type=AccessEvent.MovementType.EXIT).count(),
            allowed=PlateRegistry.objects.filter(
                list_type=PlateRegistry.ListType.WHITELIST,
                status=PlateRegistry.Status.ACTIVE,
            ).count(),
            blocked=PlateRegistry.objects.filter(
                list_type=PlateRegistry.ListType.BLACKLIST,
                status=PlateRegistry.Status.ACTIVE,
            ).count(),
            unknown=PlateRegistry.objects.filter(
                list_type=PlateRegistry.ListType.UNKNOWN,
            ).count(),
        )

        # Cameras
        all_cameras = Camera.objects.filter(is_active=True)
        cam_total = all_cameras.count()
        cam_online = all_cameras.filter(
            last_seen_at__gte=now - datetime.timedelta(minutes=5)
        ).count()
        cam_offline = cam_total - cam_online
        ctx["cameras"] = {
            "online": cam_online,
            "total": cam_total,
            "offline": cam_offline,
            "online_pct": round(cam_online / cam_total * 100, 1) if cam_total else 0,
            "last_sync": "agora",
        }

        # Gateways
        all_gateways = Gateway.objects.filter(is_active=True)
        gw_total = all_gateways.count()
        gw_online = all_gateways.filter(status=Gateway.Status.ONLINE).count()
        gw_with_queue = all_gateways.filter(pending_events__gt=0).count()
        from django.db.models import Sum as _Sum
        dlq = all_gateways.aggregate(t=_Sum("pending_events"))["t"] or 0
        ctx["gateways"] = {
            "online": gw_online,
            "total": gw_total,
            "online_pct": round(gw_online / gw_total * 100, 1) if gw_total else 0,
            "with_queue": gw_with_queue,
            "dlq_count": dlq,
        }

        # Alert summary
        open_alerts = Alert.objects.filter(status=Alert.Status.OPEN)
        ctx["alerts_summary"] = {
            "total": open_alerts.count(),
            "critical": open_alerts.filter(severity=Alert.Severity.CRITICAL).count(),
            "warning": open_alerts.filter(severity=Alert.Severity.WARNING).count(),
            "info": open_alerts.filter(severity=Alert.Severity.INFO).count(),
            "mttr": "—",
        }

        # Recent events (last 10)
        raw_events = list(
            AccessEvent.objects.select_related(
                "camera", "camera__tenant", "plate_registry"
            ).order_by("-captured_at")[:10]
        )
        ctx["events"] = [_build_event_row(ev) for ev in raw_events]

        # Critical alerts sidebar
        ctx["alerts"] = [
            _build_alert_row(a)
            for a in open_alerts.select_related("access_event")
            .order_by("-created_at")[:5]
        ]
        ctx["alert_count"] = open_alerts.count()

        # Camera and gateway panels
        ctx["camera_list"] = [
            _build_camera_row(c)
            for c in Camera.objects.filter(is_active=True)
            .select_related("tenant")
            .order_by("name")[:8]
        ]
        ctx["gateway_list"] = [
            _build_gateway_row(g)
            for g in Gateway.objects.filter(is_active=True)
            .prefetch_related("cameras")
            .order_by("name")[:8]
        ]

        # Plates tabs
        active_list = self.request.GET.get("list", "whitelist")
        ctx["active_list"] = active_list
        list_type_map = {
            "whitelist": PlateRegistry.ListType.WHITELIST,
            "blacklist": PlateRegistry.ListType.BLACKLIST,
            "unknown": PlateRegistry.ListType.UNKNOWN,
        }
        list_type = list_type_map.get(active_list, PlateRegistry.ListType.WHITELIST)
        ctx["plates"] = [
            _build_plate_row(p)
            for p in PlateRegistry.objects.filter(list_type=list_type)
            .order_by("-created_at")[:10]
        ]
        ctx["counts"] = {
            "whitelist": PlateRegistry.objects.filter(
                list_type=PlateRegistry.ListType.WHITELIST,
                status=PlateRegistry.Status.ACTIVE,
            ).count(),
            "blacklist": PlateRegistry.objects.filter(
                list_type=PlateRegistry.ListType.BLACKLIST,
                status=PlateRegistry.Status.ACTIVE,
            ).count(),
            "unknown": PlateRegistry.objects.filter(
                list_type=PlateRegistry.ListType.UNKNOWN,
            ).count(),
            "temporary": 0,
        }
        ctx["counts_active"] = ctx["counts"].get(active_list, 0)

        # Live ticker
        ticker_events = []
        for ev in AccessEvent.objects.select_related("camera").order_by("-captured_at")[:8]:
            direction = (
                "Entrada" if ev.movement_type == "entry"
                else "Saída" if ev.movement_type == "exit"
                else "Passagem"
            )
            ticker_events.append({
                "plate": ev.normalized_plate or "—",
                "summary": f"{direction} · {ev.get_decision_display()}",
                "camera": ev.camera.name if ev.camera else "—",
                "ago": _human_time(ev.captured_at),
            })
        ctx["ticker_events"] = ticker_events

        return ctx


# ---------------------------------------------------------------------------
# Section views (stub implementations — wire up real logic progressively)
# ---------------------------------------------------------------------------

class EventsView(DashboardMixin, TemplateView):
    template_name = "app/stub.html"
    active_module = "events"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = "Eventos de Placas"
        return ctx


class CamerasView(DashboardMixin, TemplateView):
    template_name = "app/stub.html"
    active_module = "cameras"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = "Câmeras"
        return ctx


class GatewaysView(DashboardMixin, TemplateView):
    template_name = "app/stub.html"
    active_module = "gateways"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = "Gateways"
        return ctx


class AlertsView(DashboardMixin, TemplateView):
    template_name = "app/stub.html"
    active_module = "alerts"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = "Alertas"
        return ctx


class PlatesView(DashboardMixin, TemplateView):
    template_name = "app/stub.html"
    active_module = "whitelist"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = "Cadastro de Placas"
        return ctx


# ---------------------------------------------------------------------------
# Utility views
# ---------------------------------------------------------------------------

class PlateSearchView(DashboardMixin, TemplateView):
    template_name = "app/stub.html"
    active_module = "events"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = f"Busca: {self.request.GET.get('q', '')}"
        return ctx


class AlertActionView(LoginRequiredMixin, View):
    """Handle POST actions (treat/resolve) on an alert."""

    login_url = "/admin/login/"

    def post(self, request, pk, *args, **kwargs):
        alert = get_object_or_404(Alert, pk=pk)
        alert.status = Alert.Status.RESOLVED
        alert.save(update_fields=["status"])
        return redirect(reverse("lpr:alerts"))
