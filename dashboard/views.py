from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.http import HttpResponseRedirect
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.timesince import timesince
from django.views.generic import TemplateView, View
from django.views.generic.edit import CreateView, UpdateView

from cameras.models import Camera, Gateway
from common.models import AuditLog, WebhookSubscription
from plates.models import AccessEvent, Alert, PlateRegistry, VehiclePresence
from tenants.models import Business, Tenant, UserTenantAccess

User = get_user_model()


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


def _ticker_events_ctx():
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
    return ticker_events


# ---------------------------------------------------------------------------
# Base mixin
# ---------------------------------------------------------------------------

class DashboardMixin(LoginRequiredMixin):
    login_url = "/app/login/"
    active_module: str = "dashboard"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.setdefault("active_module", self.active_module)
        ctx.setdefault("app_version", "4.12.0")
        ctx.setdefault("build_id", "2026.05.24")
        ctx.setdefault("environment", "development" if settings.DEBUG else "production")
        ctx.setdefault("notifications_unread", 0)
        ctx.setdefault("event_count", 0)
        ctx.setdefault("ticker_events", _ticker_events_ctx())
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

        return ctx


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

class EventsView(DashboardMixin, TemplateView):
    template_name = "app/events.html"
    active_module = "events"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        qs = AccessEvent.objects.select_related(
            "camera", "camera__tenant", "plate_registry"
        ).order_by("-captured_at")

        # Filters
        q_plate = self.request.GET.get("plate", "").strip()
        q_camera = self.request.GET.get("camera", "").strip()
        q_decision = self.request.GET.get("decision", "").strip()
        q_movement = self.request.GET.get("movement", "").strip()
        q_date_from = self.request.GET.get("date_from", "").strip()
        q_date_to = self.request.GET.get("date_to", "").strip()

        if q_plate:
            qs = qs.filter(normalized_plate__icontains=q_plate.upper())
        if q_camera:
            qs = qs.filter(camera__id=q_camera)
        if q_decision:
            qs = qs.filter(decision=q_decision)
        if q_movement:
            qs = qs.filter(movement_type=q_movement)
        if q_date_from:
            try:
                dt = datetime.datetime.strptime(q_date_from, "%Y-%m-%d")
                qs = qs.filter(captured_at__gte=timezone.make_aware(dt))
            except ValueError:
                pass
        if q_date_to:
            try:
                dt = datetime.datetime.strptime(q_date_to, "%Y-%m-%d")
                dt = dt.replace(hour=23, minute=59, second=59)
                qs = qs.filter(captured_at__lte=timezone.make_aware(dt))
            except ValueError:
                pass

        paginator = Paginator(qs, 50)
        page = self.request.GET.get("page", 1)
        page_obj = paginator.get_page(page)

        ctx["event_rows"] = [_build_event_row(ev) for ev in page_obj]
        ctx["page_obj"] = page_obj
        ctx["total_count"] = paginator.count

        ctx["cameras_for_filter"] = Camera.objects.filter(is_active=True).order_by("name")
        ctx["decisions"] = AccessEvent.Decision.choices
        ctx["movements"] = AccessEvent.MovementType.choices

        ctx["q_plate"] = q_plate
        ctx["q_camera"] = q_camera
        ctx["q_decision"] = q_decision
        ctx["q_movement"] = q_movement
        ctx["q_date_from"] = q_date_from
        ctx["q_date_to"] = q_date_to

        ctx["event_count"] = AccessEvent.objects.count()
        return ctx


# ---------------------------------------------------------------------------
# Cameras
# ---------------------------------------------------------------------------

class CamerasView(DashboardMixin, TemplateView):
    template_name = "app/cameras.html"
    active_module = "cameras"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        now = timezone.now()

        qs = Camera.objects.select_related("tenant", "gateway").order_by("name")

        q = self.request.GET.get("q", "").strip()
        q_status = self.request.GET.get("status", "").strip()
        q_mode = self.request.GET.get("mode", "").strip()

        if q:
            qs = qs.filter(name__icontains=q)
        if q_mode:
            qs = qs.filter(connection_mode=q_mode)

        cameras = list(qs)
        rows = []
        for cam in cameras:
            state = _camera_state(cam)
            if q_status and state != q_status:
                continue
            rows.append({
                "obj": cam,
                "state": state,
                "last_read_human": _human_time(cam.last_seen_at),
                "mode_display": cam.get_connection_mode_display(),
            })

        total = Camera.objects.count()
        online = Camera.objects.filter(
            is_active=True,
            last_seen_at__gte=now - datetime.timedelta(minutes=5)
        ).count()
        offline = total - online

        ctx["camera_rows"] = rows
        ctx["total"] = total
        ctx["online"] = online
        ctx["offline"] = offline
        ctx["connection_modes"] = Camera.ConnectionMode.choices
        ctx["q"] = q
        ctx["q_status"] = q_status
        ctx["q_mode"] = q_mode
        return ctx


# ---------------------------------------------------------------------------
# Gateways
# ---------------------------------------------------------------------------

class GatewaysView(DashboardMixin, TemplateView):
    template_name = "app/gateways.html"
    active_module = "gateways"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        qs = Gateway.objects.select_related("tenant").prefetch_related("cameras").order_by("name")

        q = self.request.GET.get("q", "").strip()
        q_status = self.request.GET.get("status", "").strip()

        if q:
            qs = qs.filter(name__icontains=q)
        if q_status:
            qs = qs.filter(status=q_status)

        gateways = list(qs)
        rows = []
        for gw in gateways:
            row = _build_gateway_row(gw)
            rows.append({"obj": gw, "row": row})

        total = Gateway.objects.count()
        online = Gateway.objects.filter(status=Gateway.Status.ONLINE).count()
        offline = Gateway.objects.filter(status=Gateway.Status.OFFLINE).count()

        ctx["gateway_rows"] = rows
        ctx["total"] = total
        ctx["online"] = online
        ctx["offline"] = offline
        ctx["statuses"] = Gateway.Status.choices
        ctx["q"] = q
        ctx["q_status"] = q_status
        return ctx


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------

class AlertsView(DashboardMixin, TemplateView):
    template_name = "app/alerts.html"
    active_module = "alerts"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        qs = Alert.objects.select_related(
            "access_event", "camera", "gateway", "resolved_by"
        ).order_by("-created_at")

        q_status = self.request.GET.get("status", "open")
        q_severity = self.request.GET.get("severity", "").strip()
        q_type = self.request.GET.get("type", "").strip()

        if q_status == "history":
            qs = qs.filter(status=Alert.Status.RESOLVED)
        elif q_status == "all":
            pass
        else:
            qs = qs.filter(status=Alert.Status.OPEN)

        if q_severity:
            qs = qs.filter(severity=q_severity)
        if q_type:
            qs = qs.filter(alert_type=q_type)

        paginator = Paginator(qs, 50)
        page = self.request.GET.get("page", 1)
        page_obj = paginator.get_page(page)

        rows = []
        for alert in page_obj:
            rows.append({
                "obj": alert,
                "row": _build_alert_row(alert),
                "type_label": _ALERT_TITLES.get(alert.alert_type, alert.get_alert_type_display()),
            })

        open_count = Alert.objects.filter(status=Alert.Status.OPEN).count()
        critical_count = Alert.objects.filter(
            status=Alert.Status.OPEN, severity=Alert.Severity.CRITICAL
        ).count()

        ctx["alert_rows"] = rows
        ctx["page_obj"] = page_obj
        ctx["total_count"] = paginator.count
        ctx["open_count"] = open_count
        ctx["critical_count"] = critical_count
        ctx["severities"] = Alert.Severity.choices
        ctx["alert_types"] = Alert.AlertType.choices
        ctx["alert_type_labels"] = _ALERT_TITLES
        ctx["q_status"] = q_status
        ctx["q_severity"] = q_severity
        ctx["q_type"] = q_type
        ctx["alert_count"] = open_count
        return ctx


# ---------------------------------------------------------------------------
# Vehicle Presence
# ---------------------------------------------------------------------------

class PresenceView(DashboardMixin, TemplateView):
    template_name = "app/presence.html"
    active_module = "presence"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        qs = VehiclePresence.objects.select_related(
            "tenant", "plate_registry", "last_entry_event", "last_exit_event"
        ).order_by("-last_seen_at")

        q_plate = self.request.GET.get("plate", "").strip()
        q_status = self.request.GET.get("status", "").strip()

        if q_plate:
            qs = qs.filter(normalized_plate__icontains=q_plate.upper())
        if q_status:
            qs = qs.filter(current_status=q_status)

        paginator = Paginator(qs, 50)
        page = self.request.GET.get("page", 1)
        page_obj = paginator.get_page(page)

        inside_count = VehiclePresence.objects.filter(
            current_status=VehiclePresence.CurrentStatus.INSIDE
        ).count()
        inconsistent_count = VehiclePresence.objects.filter(
            current_status=VehiclePresence.CurrentStatus.INCONSISTENT
        ).count()

        ctx["presence_rows"] = list(page_obj)
        ctx["page_obj"] = page_obj
        ctx["total_count"] = paginator.count
        ctx["inside_count"] = inside_count
        ctx["inconsistent_count"] = inconsistent_count
        ctx["statuses"] = VehiclePresence.CurrentStatus.choices
        ctx["q_plate"] = q_plate
        ctx["q_status"] = q_status
        return ctx


# ---------------------------------------------------------------------------
# Plates (dedicated full page)
# ---------------------------------------------------------------------------

class PlatesView(DashboardMixin, TemplateView):
    template_name = "app/plates.html"
    active_module = "whitelist"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        active_list = self.request.GET.get("list", "whitelist")
        q_plate = self.request.GET.get("q", "").strip()
        q_status = self.request.GET.get("status", "").strip()

        list_type_map = {
            "whitelist": PlateRegistry.ListType.WHITELIST,
            "blacklist": PlateRegistry.ListType.BLACKLIST,
            "unknown": PlateRegistry.ListType.UNKNOWN,
        }
        list_type = list_type_map.get(active_list, PlateRegistry.ListType.WHITELIST)

        qs = PlateRegistry.objects.filter(list_type=list_type).order_by("-created_at")

        if q_plate:
            qs = qs.filter(normalized_plate__icontains=q_plate.upper())
        if q_status:
            qs = qs.filter(status=q_status)

        paginator = Paginator(qs, 50)
        page = self.request.GET.get("page", 1)
        page_obj = paginator.get_page(page)

        ctx["plates"] = [_build_plate_row(p) for p in page_obj]
        ctx["plate_objects"] = list(page_obj)
        ctx["page_obj"] = page_obj
        ctx["active_list"] = active_list
        ctx["active_module"] = active_list  # highlight correct nav item
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
        ctx["counts_active"] = paginator.count
        ctx["statuses"] = PlateRegistry.Status.choices
        ctx["q_plate"] = q_plate
        ctx["q_status"] = q_status
        return ctx


# ---------------------------------------------------------------------------
# Plate detail / edit
# ---------------------------------------------------------------------------

class PlateDetailView(DashboardMixin, View):
    active_module = "whitelist"

    def _get_active_module(self, plate: PlateRegistry) -> str:
        return plate.list_type

    def get(self, request, pk):
        plate = get_object_or_404(PlateRegistry, pk=pk)
        ctx = self._base_context(plate)
        return self._render(request, ctx)

    def post(self, request, pk):
        plate = get_object_or_404(PlateRegistry, pk=pk)

        action = request.POST.get("action", "save")

        if action == "deactivate":
            plate.status = PlateRegistry.Status.INACTIVE
            plate.save(update_fields=["status", "updated_at"])
            messages.success(request, "Placa desativada com sucesso.")
            return redirect(reverse("lpr:plates") + f"?list={plate.list_type}")

        if action == "activate":
            plate.status = PlateRegistry.Status.ACTIVE
            plate.save(update_fields=["status", "updated_at"])
            messages.success(request, "Placa reativada com sucesso.")
            return redirect(reverse("lpr:plate-detail", args=[pk]))

        # Save
        plate.owner_name = request.POST.get("owner_name", "").strip()
        plate.owner_document = request.POST.get("owner_document", "").strip()
        plate.vehicle_model = request.POST.get("vehicle_model", "").strip()
        plate.vehicle_color = request.POST.get("vehicle_color", "").strip()
        plate.vehicle_type = request.POST.get("vehicle_type", "").strip()
        plate.block_reason = request.POST.get("block_reason", "").strip()
        plate.notes = request.POST.get("notes", "").strip()
        risk_level = request.POST.get("risk_level", "").strip()
        if risk_level in dict(PlateRegistry.RiskLevel.choices):
            plate.risk_level = risk_level
        valid_until_raw = request.POST.get("valid_until", "").strip()
        if valid_until_raw:
            try:
                dt = datetime.datetime.strptime(valid_until_raw, "%Y-%m-%d")
                plate.valid_until = timezone.make_aware(dt.replace(hour=23, minute=59, second=59))
            except ValueError:
                pass
        else:
            plate.valid_until = None
        plate.updated_by = request.user
        plate.save()
        messages.success(request, "Cadastro atualizado com sucesso.")
        return redirect(reverse("lpr:plate-detail", args=[pk]))

    def _base_context(self, plate: PlateRegistry) -> dict:
        from dashboard.views import DashboardMixin
        recent_events = AccessEvent.objects.filter(
            normalized_plate=plate.normalized_plate
        ).select_related("camera").order_by("-captured_at")[:10]
        return {
            "plate_obj": plate,
            "recent_events": [_build_event_row(ev) for ev in recent_events],
            "risk_levels": PlateRegistry.RiskLevel.choices,
            "statuses": PlateRegistry.Status.choices,
            "active_module": self._get_active_module(plate),
        }

    def _render(self, request, ctx: dict):
        from django.shortcuts import render
        ctx.update(self._get_mixin_context(request))
        return render(request, "app/plate_detail.html", ctx)

    def _get_mixin_context(self, request) -> dict:
        from django.utils import timezone as tz
        try:
            alert_count = Alert.objects.filter(status=Alert.Status.OPEN).count()
        except Exception:
            alert_count = 0
        return {
            "app_version": "4.12.0",
            "build_id": "2026.05.24",
            "environment": "development" if settings.DEBUG else "production",
            "notifications_unread": 0,
            "event_count": 0,
            "alert_count": alert_count,
            "ticker_events": _ticker_events_ctx(),
        }


# ---------------------------------------------------------------------------
# Event Detail
# ---------------------------------------------------------------------------

class EventDetailView(DashboardMixin, TemplateView):
    template_name = "app/event_detail.html"
    active_module = "events"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        event = get_object_or_404(
            AccessEvent.objects.select_related(
                "camera", "camera__tenant", "plate_registry",
                "plate_event", "gateway", "reviewed_by"
            ),
            pk=self.kwargs["pk"]
        )
        ctx["event"] = event
        ctx["event_row"] = _build_event_row(event)
        ctx["decisions"] = AccessEvent.Decision.choices
        ctx["movements"] = AccessEvent.MovementType.choices
        return ctx


# ---------------------------------------------------------------------------
# Event Correct Plate
# ---------------------------------------------------------------------------

class EventCorrectView(DashboardMixin, View):
    active_module = "events"

    def get(self, request, pk):
        event = get_object_or_404(AccessEvent, pk=pk)
        ctx = self._ctx(event)
        from django.shortcuts import render
        return render(request, "app/event_correct.html", ctx)

    def post(self, request, pk):
        event = get_object_or_404(AccessEvent, pk=pk)
        new_plate = request.POST.get("plate", "").strip().upper()
        reason = request.POST.get("reason", "").strip()

        if not new_plate:
            messages.error(request, "Informe a placa correta.")
            from django.shortcuts import render
            return render(request, "app/event_correct.html", self._ctx(event))

        old_plate = event.normalized_plate
        event.plate_text = new_plate
        event.normalized_plate = new_plate
        event.decision_reason = reason or "Correção manual via painel"
        event.reviewed_at = timezone.now()
        event.reviewed_by = request.user
        event.save(update_fields=[
            "plate_text", "normalized_plate", "decision_reason",
            "reviewed_at", "reviewed_by", "updated_at"
        ])

        AuditLog.objects.create(
            action="event.correct_plate",
            user=request.user,
            entity_type="AccessEvent",
            entity_id=str(event.id),
            old_value={"plate": old_plate},
            new_value={"plate": new_plate},
            reason=reason,
        )

        messages.success(request, f"Placa corrigida para {new_plate}.")
        return redirect(reverse("lpr:event-detail", args=[pk]))

    def _ctx(self, event: AccessEvent) -> dict:
        try:
            alert_count = Alert.objects.filter(status=Alert.Status.OPEN).count()
        except Exception:
            alert_count = 0
        return {
            "event": event,
            "event_row": _build_event_row(event),
            "active_module": "events",
            "app_version": "4.12.0",
            "build_id": "2026.05.24",
            "environment": "development" if settings.DEBUG else "production",
            "notifications_unread": 0,
            "event_count": 0,
            "alert_count": alert_count,
            "ticker_events": _ticker_events_ctx(),
        }


# ---------------------------------------------------------------------------
# Event Review / Change Decision
# ---------------------------------------------------------------------------

class EventReviewView(DashboardMixin, View):
    active_module = "events"

    def get(self, request, pk):
        event = get_object_or_404(AccessEvent, pk=pk)
        ctx = self._ctx(event)
        from django.shortcuts import render
        return render(request, "app/event_review.html", ctx)

    def post(self, request, pk):
        event = get_object_or_404(AccessEvent, pk=pk)
        new_decision = request.POST.get("decision", "").strip()
        reason = request.POST.get("reason", "").strip()

        if new_decision not in dict(AccessEvent.Decision.choices):
            messages.error(request, "Decisão inválida.")
            from django.shortcuts import render
            return render(request, "app/event_review.html", self._ctx(event))

        old_decision = event.decision
        event.decision = new_decision
        event.decision_reason = reason or "Revisão manual via painel"
        event.reviewed_at = timezone.now()
        event.reviewed_by = request.user
        event.save(update_fields=[
            "decision", "decision_reason", "reviewed_at", "reviewed_by", "updated_at"
        ])

        AuditLog.objects.create(
            action="event.change_decision",
            user=request.user,
            entity_type="AccessEvent",
            entity_id=str(event.id),
            old_value={"decision": old_decision},
            new_value={"decision": new_decision},
            reason=reason,
        )

        messages.success(request, "Decisão alterada com sucesso.")
        return redirect(reverse("lpr:event-detail", args=[pk]))

    def _ctx(self, event: AccessEvent) -> dict:
        try:
            alert_count = Alert.objects.filter(status=Alert.Status.OPEN).count()
        except Exception:
            alert_count = 0
        return {
            "event": event,
            "event_row": _build_event_row(event),
            "decisions": AccessEvent.Decision.choices,
            "active_module": "events",
            "app_version": "4.12.0",
            "build_id": "2026.05.24",
            "environment": "development" if settings.DEBUG else "production",
            "notifications_unread": 0,
            "event_count": 0,
            "alert_count": alert_count,
            "ticker_events": _ticker_events_ctx(),
        }


# ---------------------------------------------------------------------------
# Plate Search
# ---------------------------------------------------------------------------

class PlateSearchView(DashboardMixin, TemplateView):
    template_name = "app/plate_search.html"
    active_module = "events"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        q = self.request.GET.get("q", "").strip().upper()
        ctx["q"] = q
        ctx["page_title"] = f"Busca: {q}" if q else "Busca de Placa"

        registry_results = []
        event_results = []

        if q:
            registry_results = list(
                PlateRegistry.objects.filter(normalized_plate__icontains=q).order_by("list_type")[:20]
            )
            events_qs = AccessEvent.objects.filter(
                normalized_plate__icontains=q
            ).select_related("camera", "camera__tenant").order_by("-captured_at")[:20]
            event_results = [_build_event_row(ev) for ev in events_qs]

        ctx["registry_results"] = registry_results
        ctx["event_results"] = event_results
        ctx["has_results"] = bool(registry_results or event_results)
        return ctx


# ---------------------------------------------------------------------------
# Companies (Businesses)
# ---------------------------------------------------------------------------

class CompaniesView(DashboardMixin, TemplateView):
    template_name = "app/companies.html"
    active_module = "companies"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        qs = Business.objects.prefetch_related("tenants").order_by("name")

        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(name__icontains=q)

        paginator = Paginator(qs, 30)
        page = self.request.GET.get("page", 1)
        page_obj = paginator.get_page(page)

        rows = []
        for biz in page_obj:
            rows.append({
                "obj": biz,
                "tenant_count": biz.tenants.count(),
            })

        ctx["company_rows"] = rows
        ctx["page_obj"] = page_obj
        ctx["total_count"] = paginator.count
        ctx["q"] = q
        return ctx


# ---------------------------------------------------------------------------
# Tenants
# ---------------------------------------------------------------------------

class TenantsView(DashboardMixin, TemplateView):
    template_name = "app/tenants.html"
    active_module = "tenants"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        qs = Tenant.objects.select_related("business").order_by("business__name", "name")

        q = self.request.GET.get("q", "").strip()
        q_business = self.request.GET.get("business", "").strip()
        if q:
            qs = qs.filter(name__icontains=q)
        if q_business:
            qs = qs.filter(business_id=q_business)

        paginator = Paginator(qs, 30)
        page = self.request.GET.get("page", 1)
        page_obj = paginator.get_page(page)

        ctx["tenant_rows"] = list(page_obj)
        ctx["page_obj"] = page_obj
        ctx["total_count"] = paginator.count
        ctx["businesses"] = Business.objects.order_by("name")
        ctx["q"] = q
        ctx["q_business"] = q_business
        return ctx


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

class UsersView(DashboardMixin, TemplateView):
    template_name = "app/users.html"
    active_module = "users"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        qs = User.objects.select_related("tenant_profile", "tenant_profile__business").order_by("username")

        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(username__icontains=q) | qs.filter(email__icontains=q)

        paginator = Paginator(qs, 30)
        page = self.request.GET.get("page", 1)
        page_obj = paginator.get_page(page)

        rows = []
        for user in page_obj:
            accesses = UserTenantAccess.objects.filter(
                user=user, is_active=True
            ).select_related("business", "tenant")[:3]
            profile = getattr(user, "tenant_profile", None)
            rows.append({
                "obj": user,
                "profile": profile,
                "accesses": list(accesses),
            })

        ctx["user_rows"] = rows
        ctx["page_obj"] = page_obj
        ctx["total_count"] = paginator.count
        ctx["q"] = q
        return ctx


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------

class WebhooksView(DashboardMixin, TemplateView):
    template_name = "app/webhooks.html"
    active_module = "webhooks"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        qs = WebhookSubscription.objects.select_related("tenant").order_by("event_type", "url")

        q_tenant = self.request.GET.get("tenant", "").strip()
        q_type = self.request.GET.get("type", "").strip()
        if q_tenant:
            qs = qs.filter(tenant_id=q_tenant)
        if q_type:
            qs = qs.filter(event_type=q_type)

        paginator = Paginator(qs, 30)
        page = self.request.GET.get("page", 1)
        page_obj = paginator.get_page(page)

        active_count = WebhookSubscription.objects.filter(is_active=True).count()
        total_count = WebhookSubscription.objects.count()

        ctx["webhook_rows"] = list(page_obj)
        ctx["page_obj"] = page_obj
        ctx["total_count"] = paginator.count
        ctx["active_count"] = active_count
        ctx["inactive_count"] = total_count - active_count
        ctx["event_types"] = WebhookSubscription.EventType.choices
        ctx["tenants"] = Tenant.objects.filter(is_active=True).order_by("name")
        ctx["q_tenant"] = q_tenant
        ctx["q_type"] = q_type
        return ctx


# ---------------------------------------------------------------------------
# Audit Log
# ---------------------------------------------------------------------------

class AuditView(DashboardMixin, TemplateView):
    template_name = "app/audit.html"
    active_module = "audit"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        qs = AuditLog.objects.select_related("user", "tenant").order_by("-created_at")

        q_action = self.request.GET.get("action", "").strip()
        q_user = self.request.GET.get("user", "").strip()
        q_entity = self.request.GET.get("entity", "").strip()

        if q_action:
            qs = qs.filter(action__icontains=q_action)
        if q_user:
            qs = qs.filter(user__username__icontains=q_user)
        if q_entity:
            qs = qs.filter(entity_type__icontains=q_entity)

        paginator = Paginator(qs, 50)
        page = self.request.GET.get("page", 1)
        page_obj = paginator.get_page(page)

        ctx["audit_rows"] = list(page_obj)
        ctx["page_obj"] = page_obj
        ctx["total_count"] = paginator.count
        ctx["q_action"] = q_action
        ctx["q_user"] = q_user
        ctx["q_entity"] = q_entity
        return ctx


# ---------------------------------------------------------------------------
# LGPD
# ---------------------------------------------------------------------------

class LGPDView(DashboardMixin, TemplateView):
    template_name = "app/lgpd.html"
    active_module = "lgpd"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        try:
            from common.models import DataProcessingRecord, DataSubjectRequest, SecurityIncident
            ctx["ropt_count"] = DataProcessingRecord.objects.count()
            ctx["open_requests"] = DataSubjectRequest.objects.filter(status="open").count()
            ctx["open_incidents"] = SecurityIncident.objects.filter(status="open").count()
            ctx["has_lgpd_models"] = True
        except Exception:
            ctx["has_lgpd_models"] = False
            ctx["ropt_count"] = 0
            ctx["open_requests"] = 0
            ctx["open_incidents"] = 0

        return ctx


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

class SettingsView(DashboardMixin, TemplateView):
    template_name = "app/settings.html"
    active_module = "settings"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        try:
            from common.mlops import active_model_metadata
            yolo_meta = active_model_metadata("yolo")
            ocr_meta = active_model_metadata("ocr")
        except Exception:
            yolo_meta = None
            ocr_meta = None

        ctx["yolo_meta"] = yolo_meta
        ctx["ocr_meta"] = ocr_meta
        ctx["django_debug"] = settings.DEBUG
        ctx["celery_eager"] = getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False)

        try:
            from common.models import DeadLetterTask
            ctx["dlq_pending"] = DeadLetterTask.objects.filter(status="pending").count()
        except Exception:
            ctx["dlq_pending"] = 0

        return ctx


# ---------------------------------------------------------------------------
# Tenant Switch
# ---------------------------------------------------------------------------

class TenantSwitchView(DashboardMixin, TemplateView):
    template_name = "app/tenant_switch.html"
    active_module = "tenants"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user

        if user.is_superuser:
            tenants = Tenant.objects.select_related("business").filter(is_active=True).order_by("business__name", "name")
        else:
            accesses = UserTenantAccess.objects.filter(
                user=user, is_active=True
            ).select_related("tenant", "tenant__business")
            tenant_ids = set()
            for acc in accesses:
                if acc.tenant_id:
                    tenant_ids.add(acc.tenant_id)
            tenants = Tenant.objects.select_related("business").filter(
                id__in=tenant_ids, is_active=True
            ).order_by("business__name", "name")

        ctx["available_tenants"] = list(tenants)
        return ctx


# ---------------------------------------------------------------------------
# Plates Import
# ---------------------------------------------------------------------------

class PlateImportView(DashboardMixin, TemplateView):
    template_name = "app/plates_import.html"
    active_module = "whitelist"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["tenants"] = Tenant.objects.filter(is_active=True).order_by("name")
        return ctx


# ---------------------------------------------------------------------------
# Utility views
# ---------------------------------------------------------------------------

class EventQuickRegisterView(DashboardMixin, View):
    """
    Registra rapidamente uma placa como whitelist ou blacklist a partir de
    um evento desconhecido, atualizando a decisão do evento e resolvendo
    os alertas abertos relacionados.
    """

    def post(self, request, pk):
        import re as _re
        from plates.models import AccessEvent, PlateRegistry, Alert

        event = get_object_or_404(AccessEvent, pk=pk)
        list_type = request.POST.get("list_type", "").strip()

        if list_type not in ("whitelist", "blacklist"):
            messages.error(request, "Tipo de lista inválido.")
            return redirect(reverse("lpr:event-detail", args=[pk]))

        normalized = _re.sub(r"[^A-Z0-9]", "", event.plate_text.upper())
        if not normalized:
            messages.error(request, "Evento sem placa identificada.")
            return redirect(reverse("lpr:event-detail", args=[pk]))

        tenant = event.camera.tenant if event.camera_id else None

        # Remove entradas antigas whitelist/blacklist da mesma placa/tenant
        PlateRegistry.objects.filter(
            normalized_plate=normalized,
            tenant=tenant,
            list_type__in=[PlateRegistry.ListType.WHITELIST, PlateRegistry.ListType.BLACKLIST],
        ).update(status=PlateRegistry.Status.INACTIVE)

        registry, _ = PlateRegistry.objects.get_or_create(
            normalized_plate=normalized,
            tenant=tenant,
            list_type=list_type,
            defaults={
                "plate":      event.plate_text,
                "status":     PlateRegistry.Status.ACTIVE,
                "created_by": request.user,
                "updated_by": request.user,
            },
        )
        # Garante que o registro está ativo (caso já existisse inativo)
        if registry.status != PlateRegistry.Status.ACTIVE:
            registry.status = PlateRegistry.Status.ACTIVE
            registry.updated_by = request.user
            registry.save(update_fields=["status", "updated_by"])

        new_decision = (
            AccessEvent.Decision.ALLOWED if list_type == "whitelist"
            else AccessEvent.Decision.BLOCKED
        )
        event.decision         = new_decision
        event.list_type_result = list_type
        event.plate_registry   = registry
        event.save(update_fields=["decision", "list_type_result", "plate_registry"])

        Alert.objects.filter(
            plate=normalized,
            alert_type="unknown_plate_detected",
            status=Alert.Status.OPEN,
        ).update(
            status=Alert.Status.RESOLVED,
            resolved_by=request.user,
            resolved_at=timezone.now(),
        )

        label = "Whitelist" if list_type == "whitelist" else "Blacklist"
        messages.success(request, f"Placa {event.plate_text} adicionada à {label}.")
        return redirect(reverse("lpr:event-detail", args=[pk]))


class AlertActionView(LoginRequiredMixin, View):
    """Handle POST actions (treat/resolve) on an alert."""

    login_url = "/app/login/"

    def post(self, request, pk, *args, **kwargs):
        alert = get_object_or_404(Alert, pk=pk)
        alert.status = Alert.Status.RESOLVED
        alert.resolved_by = request.user
        alert.resolved_at = timezone.now()
        alert.save(update_fields=["status", "resolved_by", "resolved_at"])
        return redirect(reverse("lpr:alerts"))


# ---------------------------------------------------------------------------
# App-level auth (separate from Django admin)
# ---------------------------------------------------------------------------

class AppLoginView(View):
    """Login page for /app/ section — distinct from /admin/ login."""

    template_name = "app/login.html"

    def get(self, request):
        if request.user.is_authenticated:
            return redirect(reverse("lpr:dashboard"))
        next_url = request.GET.get("next", reverse("lpr:dashboard"))
        return render(request, self.template_name, {"next": next_url})

    def post(self, request):
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        next_url = request.POST.get("next", reverse("lpr:dashboard"))

        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect(next_url)

        return render(request, self.template_name, {
            "error": "Usuário ou senha inválidos.",
            "username": username,
            "next": next_url,
        })


class AppLogoutView(View):
    """Logout from /app/ section."""

    def post(self, request):
        logout(request)
        return redirect(reverse("lpr:login"))

    def get(self, request):
        logout(request)
        return redirect(reverse("lpr:login"))


# ---------------------------------------------------------------------------
# Profile edit (logged-in user's own data)
# ---------------------------------------------------------------------------

class ProfileEditView(DashboardMixin, TemplateView):
    template_name = "app/profile_edit.html"
    active_module = "dashboard"

    def get_context_data(self, **kwargs):
        from dashboard.forms import ProfileForm
        ctx = super().get_context_data(**kwargs)
        ctx["form"] = ProfileForm(instance=self.request.user)
        return ctx

    def post(self, request, *args, **kwargs):
        from dashboard.forms import ProfileForm
        form = ProfileForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Perfil atualizado com sucesso.")
            return redirect(reverse("lpr:profile"))
        ctx = self.get_context_data()
        ctx["form"] = form
        return render(request, self.template_name, ctx)


# ---------------------------------------------------------------------------
# Generic CRUD mixin for app-level create/edit views
# ---------------------------------------------------------------------------

class _CrudMixin(DashboardMixin):
    """Shared behaviour for CreateView / UpdateView subclasses."""
    template_name = "app/crud_form.html"
    form_title: str = ""
    cancel_url_name: str = ""
    active_module: str = "dashboard"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["form_title"] = self.form_title
        ctx["cancel_url"] = reverse(f"lpr:{self.cancel_url_name}")
        return ctx

    def form_valid(self, form):
        messages.success(self.request, "Salvo com sucesso.")
        return super().form_valid(form)


# ---------------------------------------------------------------------------
# Live Status API  (polling JSON — sem autenticação dupla, só LoginRequired)
# ---------------------------------------------------------------------------

class LiveStatusAPIView(LoginRequiredMixin, View):
    """
    GET /app/api/live-status/
    Consulta a API REST do MediaMTX, atualiza last_seen_at das câmeras com
    stream ativo e retorna JSON com estado de cada câmera + contagem de alertas.
    Responde em < 2 s mesmo quando o MediaMTX estiver offline.
    """
    login_url = "/app/login/"

    def get(self, request):
        import requests as _http

        api_port = getattr(settings, "MEDIAMTX_API_PORT", 9997)
        active_paths: set[str] = set()
        mediamtx_ok = False

        try:
            r = _http.get(
                f"http://127.0.0.1:{api_port}/v3/paths/list",
                timeout=1.5,
            )
            if r.ok:
                mediamtx_ok = True
                for item in r.json().get("items", []):
                    if item.get("ready"):
                        active_paths.add(item.get("name", ""))
        except Exception:
            pass  # MediaMTX offline → usamos apenas last_seen_at

        now = timezone.now()
        cameras = list(Camera.objects.filter(is_active=True).select_related("tenant"))

        # Atualiza last_seen_at para câmeras com stream ativo agora
        if active_paths:
            live_ids = [
                cam.pk for cam in cameras
                if f"live/{cam.camera_key}" in active_paths
                and cam.connection_mode != Camera.ConnectionMode.PUSH
            ]
            if live_ids:
                Camera.objects.filter(pk__in=live_ids).update(last_seen_at=now)
                live_id_set = set(live_ids)
                for cam in cameras:
                    if cam.pk in live_id_set:
                        cam.last_seen_at = now

        cam_data = []
        for cam in cameras:
            mediamtx_live = (
                f"live/{cam.camera_key}" in active_paths
                and cam.connection_mode != Camera.ConnectionMode.PUSH
            )
            state = "online" if mediamtx_live else _camera_state(cam)
            cam_data.append({
                "id": cam.id,
                "name": cam.name,
                "state": state,
                "mediamtx_live": mediamtx_live,
                "last_seen_human": _human_time(cam.last_seen_at),
            })

        online_n = sum(1 for c in cam_data if c["state"] == "online")
        offline_n = sum(1 for c in cam_data if c["state"] == "offline")

        try:
            alert_count = Alert.objects.filter(status=Alert.Status.OPEN).count()
        except Exception:
            alert_count = 0

        return JsonResponse({
            "cameras": cam_data,
            "summary": {
                "online": online_n,
                "offline": offline_n,
                "total": len(cam_data),
            },
            "alert_count": alert_count,
            "mediamtx_ok": mediamtx_ok,
        })


class LiveEventsAPIView(LoginRequiredMixin, View):
    """
    GET /app/api/events/poll/?since_id=<int>
    Retorna eventos capturados após since_id (ou últimos 10 se since_id=0).
    Usado para o ticker ao vivo e notificações push do topbar.
    """
    login_url = "/app/login/"

    def get(self, request):
        since_id = int(request.GET.get("since_id", 0))

        qs = (
            AccessEvent.objects
            .select_related("camera", "plate_registry")
            .order_by("-id")
        )
        if since_id > 0:
            qs = qs.filter(id__gt=since_id)

        events = list(qs[:20])

        result = []
        for ev in events:
            plate = ev.normalized_plate or ev.plate_text or "—"
            direction = (
                "Entrada" if ev.movement_type == AccessEvent.MovementType.ENTRY
                else "Saída" if ev.movement_type == AccessEvent.MovementType.EXIT
                else "Passagem"
            )
            result.append({
                "id": ev.id,
                "plate": plate,
                "camera": ev.camera.name if ev.camera else "—",
                "decision": ev.decision or "unknown",
                "decision_label": ev.get_decision_display(),
                "direction": direction,
                "ago": _human_time(ev.captured_at),
                "summary": f"{direction} · {ev.get_decision_display()}",
            })

        return JsonResponse({
            "events": result,
            "max_id": events[0].id if events else since_id,
            "count": len(result),
        })


# ---------------------------------------------------------------------------
# Live Camera Events API  (polling por câmera — usado na tela de live)
# ---------------------------------------------------------------------------

class LiveCameraEventsAPIView(LoginRequiredMixin, View):
    """
    GET /app/api/cameras/<pk>/events/?since_id=<int>
    Retorna eventos recentes de uma câmera específica para o painel de
    detecções ao vivo. since_id=0 → últimos 20; since_id>0 → apenas novos.
    """
    login_url = "/app/login/"

    def get(self, request, pk):
        camera = get_object_or_404(Camera, pk=pk)
        since_id = int(request.GET.get("since_id", 0))

        qs = (
            AccessEvent.objects
            .filter(camera=camera)
            .select_related("plate_registry")
            .order_by("-id")
        )
        if since_id > 0:
            qs = qs.filter(id__gt=since_id)

        events = list(qs[:20])

        result = []
        for ev in events:
            plate = ev.normalized_plate or ev.plate_text or "—"

            # Tipo de lista (whitelist / blacklist / unknown)
            if ev.list_type_result:
                list_type = ev.list_type_result
            elif ev.plate_registry:
                list_type = ev.plate_registry.list_type
            else:
                list_type = "unknown"

            # URL do crop (preferência) ou frame completo
            crop_url = None
            if ev.crop_image:
                crop_url = request.build_absolute_uri(ev.crop_image.url)
            elif ev.image:
                crop_url = request.build_absolute_uri(ev.image.url)

            confidence = float(ev.confidence) if ev.confidence else 0.0

            result.append({
                "id":            ev.id,
                "plate":         plate,
                "decision":      ev.decision or "unknown",
                "decision_label": ev.get_decision_display(),
                "list_type":     list_type,
                "confidence":    round(confidence * 100),
                "ago":           _human_time(ev.captured_at),
                "crop_url":      crop_url,
                "event_url":     reverse("lpr:event-detail", args=[ev.id]),
            })

        return JsonResponse({
            "events":  result,
            "max_id":  events[0].id if events else since_id,
            "count":   len(result),
        })


# ---------------------------------------------------------------------------
# Camera Live View
# ---------------------------------------------------------------------------

class CameraLiveView(DashboardMixin, TemplateView):
    """Página dedicada ao player de vídeo ao vivo de uma câmera."""
    template_name = "app/camera_live.html"
    active_module = "cameras"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        camera = get_object_or_404(Camera, pk=self.kwargs["pk"])

        hls_host = settings.MEDIAMTX_HOST
        hls_port = settings.MEDIAMTX_HLS_PORT

        # URL base HLS: usa URL pública (ngrok) quando configurada,
        # senão usa host:porta locais.
        hls_public = getattr(settings, "MEDIAMTX_HLS_PUBLIC_URL", "")
        hls_base   = hls_public or f"http://{hls_host}:{hls_port}"
        hls_url    = f"{hls_base}/live/{camera.camera_key}/index.m3u8"

        # URL pública RTMP para exibir na página de instruções de câmera
        rtmp_public  = getattr(settings, "MEDIAMTX_RTMP_PUBLIC_URL", "")
        rtmp_port    = getattr(settings, "MEDIAMTX_RTMP_PORT",  1935)
        rtmp_local   = f"rtmp://{hls_host}:{rtmp_port}"
        rtmp_display = rtmp_public or rtmp_local

        # Para câmeras PUSH (frame-a-frame HTTP) não há stream MediaMTX
        has_stream = camera.connection_mode != Camera.ConnectionMode.PUSH
        state = _camera_state(camera)

        # Último frame capturado — exibido no player quando o stream não carrega
        from plates.models import AccessEvent
        last_event = (
            AccessEvent.objects
            .filter(camera=camera)
            .exclude(image="")
            .order_by("-received_at")
            .first()
        )
        last_frame_url = last_event.image.url if last_event and last_event.image else ""

        ctx["camera"]          = camera
        ctx["hls_url"]         = hls_url
        ctx["hls_host"]        = hls_host
        ctx["hls_port"]        = hls_port
        ctx["hls_public_url"]  = hls_public
        ctx["rtmp_display"]    = rtmp_display
        ctx["has_stream"]      = has_stream
        ctx["camera_state"]    = state
        ctx["last_seen_human"] = _human_time(camera.last_seen_at)
        ctx["last_frame_url"]  = last_frame_url
        return ctx


# ---------------------------------------------------------------------------
# Cameras CRUD
# ---------------------------------------------------------------------------

class CameraCreateView(_CrudMixin, CreateView):
    from cameras.models import Camera as _Camera
    model = _Camera
    form_title = "Nova câmera"
    cancel_url_name = "cameras"
    active_module = "cameras"

    def get_form_class(self):
        from dashboard.forms import CameraForm
        return CameraForm

    def get_success_url(self):
        return reverse("lpr:cameras")


class CameraEditView(_CrudMixin, UpdateView):
    from cameras.models import Camera as _Camera
    model = _Camera
    form_title = "Editar câmera"
    cancel_url_name = "cameras"
    active_module = "cameras"

    def get_form_class(self):
        from dashboard.forms import CameraForm
        return CameraForm

    def get_success_url(self):
        return reverse("lpr:cameras")


# ---------------------------------------------------------------------------
# Gateways CRUD
# ---------------------------------------------------------------------------

class GatewayCreateView(_CrudMixin, CreateView):
    from cameras.models import Gateway as _Gateway
    model = _Gateway
    form_title = "Novo gateway"
    cancel_url_name = "gateways"
    active_module = "gateways"

    def get_form_class(self):
        from dashboard.forms import GatewayForm
        return GatewayForm

    def get_success_url(self):
        return reverse("lpr:gateways")


class GatewayEditView(_CrudMixin, UpdateView):
    from cameras.models import Gateway as _Gateway
    model = _Gateway
    form_title = "Editar gateway"
    cancel_url_name = "gateways"
    active_module = "gateways"

    def get_form_class(self):
        from dashboard.forms import GatewayForm
        return GatewayForm

    def get_success_url(self):
        return reverse("lpr:gateways")


# ---------------------------------------------------------------------------
# Companies (Business) CRUD
# ---------------------------------------------------------------------------

class CompanyCreateView(_CrudMixin, CreateView):
    from tenants.models import Business as _Business
    model = _Business
    form_title = "Nova empresa"
    cancel_url_name = "companies"
    active_module = "companies"

    def get_form_class(self):
        from dashboard.forms import BusinessForm
        return BusinessForm

    def get_success_url(self):
        return reverse("lpr:companies")


class CompanyEditView(_CrudMixin, UpdateView):
    from tenants.models import Business as _Business
    model = _Business
    form_title = "Editar empresa"
    cancel_url_name = "companies"
    active_module = "companies"

    def get_form_class(self):
        from dashboard.forms import BusinessForm
        return BusinessForm

    def get_success_url(self):
        return reverse("lpr:companies")


# ---------------------------------------------------------------------------
# Tenants CRUD
# ---------------------------------------------------------------------------

class TenantCreateView(_CrudMixin, CreateView):
    from tenants.models import Tenant as _Tenant
    model = _Tenant
    form_title = "Nova unidade (tenant)"
    cancel_url_name = "tenants"
    active_module = "tenants"

    def get_form_class(self):
        from dashboard.forms import TenantForm
        return TenantForm

    def get_success_url(self):
        return reverse("lpr:tenants")


class TenantEditView(_CrudMixin, UpdateView):
    from tenants.models import Tenant as _Tenant
    model = _Tenant
    form_title = "Editar unidade (tenant)"
    cancel_url_name = "tenants"
    active_module = "tenants"

    def get_form_class(self):
        from dashboard.forms import TenantForm
        return TenantForm

    def get_success_url(self):
        return reverse("lpr:tenants")


# ---------------------------------------------------------------------------
# Users CRUD
# ---------------------------------------------------------------------------

class UserCreateView(_CrudMixin, CreateView):
    model = User
    form_title = "Novo usuário"
    cancel_url_name = "users"
    active_module = "users"

    def get_form_class(self):
        from dashboard.forms import UserCreateForm
        return UserCreateForm

    def get_success_url(self):
        return reverse("lpr:users")


class UserEditView(_CrudMixin, UpdateView):
    model = User
    form_title = "Editar usuário"
    cancel_url_name = "users"
    active_module = "users"

    def get_form_class(self):
        from dashboard.forms import UserEditForm
        return UserEditForm

    def get_success_url(self):
        return reverse("lpr:users")


# ---------------------------------------------------------------------------
# Webhooks CRUD
# ---------------------------------------------------------------------------

class WebhookCreateView(_CrudMixin, CreateView):
    from common.models import WebhookSubscription as _Wh
    model = _Wh
    form_title = "Novo webhook"
    cancel_url_name = "webhooks"
    active_module = "webhooks"

    def get_form_class(self):
        from dashboard.forms import WebhookForm
        return WebhookForm

    def get_success_url(self):
        return reverse("lpr:webhooks")


class WebhookEditView(_CrudMixin, UpdateView):
    from common.models import WebhookSubscription as _Wh
    model = _Wh
    form_title = "Editar webhook"
    cancel_url_name = "webhooks"
    active_module = "webhooks"

    def get_form_class(self):
        from dashboard.forms import WebhookForm
        return WebhookForm

    def get_success_url(self):
        return reverse("lpr:webhooks")


# ---------------------------------------------------------------------------
# Plate create (single)
# ---------------------------------------------------------------------------

class PlateCreateView(_CrudMixin, CreateView):
    from plates.models import PlateRegistry as _PR
    model = _PR
    form_title = "Cadastrar placa"
    cancel_url_name = "plates"
    active_module = "whitelist"

    def get_form_class(self):
        from dashboard.forms import PlateCreateForm
        return PlateCreateForm

    def get_success_url(self):
        return reverse("lpr:plate-detail", args=[self.object.pk])
