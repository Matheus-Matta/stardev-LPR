"""
Management command: createadminuser

Cria (ou atualiza, se já existir) o superusuário Django e os registros
iniciais de Business, Tenant e UserTenantAccess a partir das variáveis
de ambiente definidas no .env.

Uso:
    python manage.py createadminuser
    python manage.py createadminuser --no-input   # não faz perguntas interativas

Variáveis lidas do .env / ambiente:
    SUPERUSER_USERNAME     (padrão: "admin")
    SUPERUSER_EMAIL        (padrão: "admin@localhost")
    SUPERUSER_PASSWORD     (obrigatório se não for fornecido via --password)
    SETUP_BUSINESS_NAME    (padrão: "starLPR")
    SETUP_BUSINESS_LEGAL_NAME  (padrão: mesmo que SETUP_BUSINESS_NAME)
    SETUP_BUSINESS_DOCUMENT    (padrão: "")
    SETUP_TENANT_NAME      (padrão: "Unidade Principal")
    SETUP_TENANT_SLUG      (padrão: derivado automaticamente de SETUP_TENANT_NAME)
    SETUP_TENANT_LOCATION  (padrão: "")
    SETUP_TENANT_TIMEZONE  (padrão: "America/Sao_Paulo")
"""

import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils.text import slugify

from tenants.models import Business, Tenant, UserProfile, UserTenantAccess

User = get_user_model()


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


class Command(BaseCommand):
    help = "Cria superusuário + Business + Tenant a partir das variáveis do .env"

    def add_arguments(self, parser):
        parser.add_argument(
            "--username",
            default=None,
            help="Username do superusuário (sobrescreve SUPERUSER_USERNAME)",
        )
        parser.add_argument(
            "--email",
            default=None,
            help="E-mail do superusuário (sobrescreve SUPERUSER_EMAIL)",
        )
        parser.add_argument(
            "--password",
            default=None,
            help="Senha do superusuário (sobrescreve SUPERUSER_PASSWORD)",
        )
        parser.add_argument(
            "--no-input",
            action="store_true",
            dest="no_input",
            help="Não faz perguntas interativas; falha se SUPERUSER_PASSWORD não estiver definida",
        )

    def handle(self, *args, **options):
        no_input = options["no_input"]

        # ── Superusuário ──────────────────────────────────────────────────
        username = options["username"] or _env("SUPERUSER_USERNAME", "admin")
        email    = options["email"]    or _env("SUPERUSER_EMAIL", "admin@localhost")
        password = options["password"] or _env("SUPERUSER_PASSWORD")

        if not password:
            if no_input:
                raise CommandError(
                    "SUPERUSER_PASSWORD não definida no .env e --no-input foi passado."
                )
            import getpass
            password = getpass.getpass(f"Senha para '{username}': ")
            if not password:
                raise CommandError("Senha não pode ser vazia.")

        user, user_created = User.objects.get_or_create(
            username=username,
            defaults={"email": email},
        )
        user.email = email
        user.is_staff = True
        user.is_superuser = True
        user.set_password(password)
        user.save()

        verb = "Criado" if user_created else "Atualizado"
        self.stdout.write(self.style.SUCCESS(f"✓ Superusuário {verb}: {username} <{email}>"))

        # ── Business ──────────────────────────────────────────────────────
        biz_name       = _env("SETUP_BUSINESS_NAME", "starLPR")
        biz_legal_name = _env("SETUP_BUSINESS_LEGAL_NAME", biz_name)
        biz_document   = _env("SETUP_BUSINESS_DOCUMENT", "")

        business, biz_created = Business.objects.get_or_create(
            name=biz_name,
            defaults={
                "legal_name": biz_legal_name,
                "document":   biz_document,
                "is_active":  True,
            },
        )
        if not biz_created:
            # Atualiza campos que podem ter mudado no .env
            changed = False
            if biz_legal_name and business.legal_name != biz_legal_name:
                business.legal_name = biz_legal_name
                changed = True
            if biz_document and business.document != biz_document:
                business.document = biz_document
                changed = True
            if changed:
                business.save()

        verb = "Criado" if biz_created else "Já existente"
        self.stdout.write(self.style.SUCCESS(f"✓ Business {verb}: {business}"))

        # ── Tenant ────────────────────────────────────────────────────────
        tenant_name     = _env("SETUP_TENANT_NAME", "Unidade Principal")
        tenant_slug     = _env("SETUP_TENANT_SLUG", "") or slugify(tenant_name)
        tenant_location = _env("SETUP_TENANT_LOCATION", "")
        tenant_timezone = _env("SETUP_TENANT_TIMEZONE", "America/Sao_Paulo")

        tenant, ten_created = Tenant.objects.get_or_create(
            slug=tenant_slug,
            defaults={
                "business":  business,
                "name":      tenant_name,
                "location":  tenant_location,
                "timezone":  tenant_timezone,
                "is_active": True,
            },
        )
        if not ten_created and tenant.business != business:
            # Garante que o tenant está vinculado ao business correto
            tenant.business = business
            tenant.save()

        verb = "Criado" if ten_created else "Já existente"
        self.stdout.write(self.style.SUCCESS(f"✓ Tenant {verb}: {tenant} (slug: {tenant.slug})"))

        # ── UserProfile ───────────────────────────────────────────────────
        profile, prof_created = UserProfile.objects.get_or_create(
            user=user,
            defaults={"business": business, "is_admin": True},
        )
        if not prof_created and profile.business != business:
            profile.business = business
            profile.is_admin = True
            profile.save()

        verb = "Criado" if prof_created else "Já existente"
        self.stdout.write(self.style.SUCCESS(f"✓ UserProfile {verb} para {user.username}"))

        # ── UserTenantAccess ──────────────────────────────────────────────
        access, acc_created = UserTenantAccess.objects.get_or_create(
            user=user,
            business=business,
            tenant=None,           # None = acesso a todos os tenants do business
            defaults={"role": UserTenantAccess.Role.OWNER, "is_active": True},
        )
        if not acc_created and access.role != UserTenantAccess.Role.OWNER:
            access.role = UserTenantAccess.Role.OWNER
            access.is_active = True
            access.save()

        verb = "Criado" if acc_created else "Já existente"
        self.stdout.write(self.style.SUCCESS(f"✓ UserTenantAccess {verb}: OWNER em {business.name}"))

        # ── Resumo ────────────────────────────────────────────────────────
        self.stdout.write("")
        self.stdout.write(self.style.HTTP_INFO("─" * 50))
        self.stdout.write(self.style.HTTP_INFO("createadminuser concluido."))
        self.stdout.write(f"  Acesse em: /app/  (login: {username})")
        self.stdout.write(self.style.HTTP_INFO("─" * 50))
