from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

from cameras.models import Camera, Gateway
from common.models import WebhookSubscription
from plates.models import PlateRegistry
from tenants.models import Business, Tenant

User = get_user_model()

_INPUT = (
    "w-full h-10 px-3 rounded-lg border border-ink-200 bg-ink-50 text-[13px] "
    "text-ink-900 placeholder:text-ink-300 focus:outline-none focus:border-brand-400 "
    "focus:ring-2 focus:ring-brand-100 transition"
)
_SELECT = (
    "w-full h-10 px-3 rounded-lg border border-ink-200 bg-ink-50 text-[13px] "
    "text-ink-900 focus:outline-none focus:border-brand-400 transition"
)
_TEXTAREA = (
    "w-full px-3 py-2 rounded-lg border border-ink-200 bg-ink-50 text-[13px] "
    "text-ink-900 focus:outline-none focus:border-brand-400 focus:ring-2 "
    "focus:ring-brand-100 transition"
)
_CHECK = "w-4 h-4 rounded border-ink-300 text-brand-600 focus:ring-brand-400"


class _TailwindMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            w = field.widget
            if isinstance(w, forms.CheckboxInput):
                w.attrs.setdefault("class", _CHECK)
            elif isinstance(w, (forms.Select, forms.SelectMultiple)):
                w.attrs.setdefault("class", _SELECT)
            elif isinstance(w, forms.Textarea):
                w.attrs.setdefault("class", _TEXTAREA)
                w.attrs.setdefault("rows", 3)
            else:
                w.attrs.setdefault("class", _INPUT)


# ---------------------------------------------------------------------------
# Cameras / Gateways
# ---------------------------------------------------------------------------

class GatewayForm(_TailwindMixin, forms.ModelForm):
    class Meta:
        model = Gateway
        fields = ["name", "tenant", "location", "is_active"]
        labels = {
            "name": "Nome",
            "tenant": "Unidade (tenant)",
            "location": "Localização",
            "is_active": "Ativo",
        }


class CameraForm(_TailwindMixin, forms.ModelForm):
    class Meta:
        model = Camera
        fields = [
            "name", "tenant", "gateway", "connection_mode", "direction_default",
            "location", "host", "port", "rtsp_path", "username", "timezone", "is_active",
        ]
        labels = {
            "name": "Nome",
            "tenant": "Unidade (tenant)",
            "gateway": "Gateway",
            "connection_mode": "Modo de conexão",
            "direction_default": "Direção padrão",
            "location": "Localização",
            "host": "Host / IP",
            "port": "Porta",
            "rtsp_path": "Caminho RTSP",
            "username": "Usuário RTSP",
            "timezone": "Fuso horário",
            "is_active": "Ativo",
        }


# ---------------------------------------------------------------------------
# Tenancy
# ---------------------------------------------------------------------------

class BusinessForm(_TailwindMixin, forms.ModelForm):
    class Meta:
        model = Business
        fields = ["name", "legal_name", "document", "is_active"]
        labels = {
            "name": "Nome",
            "legal_name": "Razão social",
            "document": "CNPJ",
            "is_active": "Ativo",
        }


class TenantForm(_TailwindMixin, forms.ModelForm):
    class Meta:
        model = Tenant
        fields = ["business", "name", "slug", "document", "location", "timezone", "is_active"]
        labels = {
            "business": "Empresa",
            "name": "Nome",
            "slug": "Slug (URL)",
            "document": "CNPJ / documento",
            "location": "Endereço / localização",
            "timezone": "Fuso horário",
            "is_active": "Ativo",
        }


class UserCreateForm(_TailwindMixin, UserCreationForm):
    tenant = forms.ModelChoiceField(
        queryset=Tenant.objects.filter(is_active=True).order_by("name"),
        required=False,
        label="Unidade (tenant)",
        empty_label="— Nenhuma —",
    )
    is_admin = forms.BooleanField(required=False, label="Administrador da empresa")

    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "email", "password1", "password2", "tenant", "is_admin"]
        labels = {
            "username": "Usuário",
            "first_name": "Nome",
            "last_name": "Sobrenome",
            "email": "E-mail",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["password1"].label = "Senha"
        self.fields["password2"].label = "Confirmar senha"

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            from tenants.models import UserProfile, UserTenantAccess
            tenant = self.cleaned_data.get("tenant")
            is_admin = self.cleaned_data.get("is_admin", False)
            business = tenant.business if tenant else None
            UserProfile.objects.update_or_create(
                user=user,
                defaults={"business": business, "is_admin": is_admin},
            )
            if tenant:
                UserTenantAccess.objects.get_or_create(
                    user=user, business=business, tenant=tenant,
                    defaults={"role": "operator", "is_active": True},
                )
        return user


class UserEditForm(_TailwindMixin, forms.ModelForm):
    tenant = forms.ModelChoiceField(
        queryset=Tenant.objects.filter(is_active=True).order_by("name"),
        required=False,
        label="Unidade (tenant)",
        empty_label="— Nenhuma —",
    )
    is_admin = forms.BooleanField(required=False, label="Administrador da empresa")

    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "email", "is_active", "tenant", "is_admin"]
        labels = {
            "username": "Usuário",
            "first_name": "Nome",
            "last_name": "Sobrenome",
            "email": "E-mail",
            "is_active": "Ativo",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            from tenants.models import UserProfile, UserTenantAccess
            try:
                profile = self.instance.tenant_profile
                self.fields["is_admin"].initial = profile.is_admin
                access = UserTenantAccess.objects.filter(user=self.instance, is_active=True).first()
                if access:
                    self.fields["tenant"].initial = access.tenant
            except Exception:
                pass

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            from tenants.models import UserProfile, UserTenantAccess
            tenant = self.cleaned_data.get("tenant")
            is_admin = self.cleaned_data.get("is_admin", False)
            business = tenant.business if tenant else None
            UserProfile.objects.update_or_create(
                user=user,
                defaults={"business": business, "is_admin": is_admin},
            )
            if tenant:
                UserTenantAccess.objects.update_or_create(
                    user=user, business=business, tenant=tenant,
                    defaults={"role": "operator", "is_active": True},
                )
        return user


class ProfileForm(_TailwindMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "email"]
        labels = {
            "first_name": "Nome",
            "last_name": "Sobrenome",
            "email": "E-mail",
        }


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------

class WebhookForm(_TailwindMixin, forms.ModelForm):
    class Meta:
        model = WebhookSubscription
        fields = ["url", "tenant", "event_type", "is_active"]
        labels = {
            "url": "URL de destino",
            "tenant": "Unidade (tenant)",
            "event_type": "Tipo de evento",
            "is_active": "Ativo",
        }


# ---------------------------------------------------------------------------
# Plates
# ---------------------------------------------------------------------------

class PlateCreateForm(_TailwindMixin, forms.ModelForm):
    class Meta:
        model = PlateRegistry
        fields = [
            "plate", "tenant", "list_type", "status",
            "owner_name", "owner_document", "vehicle_model", "vehicle_color",
            "valid_until", "block_reason", "risk_level",
        ]
        labels = {
            "plate": "Placa",
            "tenant": "Unidade (tenant)",
            "list_type": "Lista",
            "status": "Status",
            "owner_name": "Responsável",
            "owner_document": "CPF / CNPJ",
            "vehicle_model": "Modelo do veículo",
            "vehicle_color": "Cor",
            "valid_until": "Válido até",
            "block_reason": "Motivo do bloqueio",
            "risk_level": "Nível de risco",
        }
        widgets = {
            "valid_until": forms.DateInput(attrs={"type": "date"}),
        }
