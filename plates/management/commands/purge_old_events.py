from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from plates.models import AccessEvent, PlateEvent
from plates.tasks import _delete_image_field


class Command(BaseCommand):
    help = (
        "Purga eventos e/ou imagens antigas.\n"
        "  --days: deleta registros PlateEvent mais antigos que N dias (padrão: EVENT_RETENTION_DAYS).\n"
        "  --image-hours: deleta só os arquivos PNG mais antigos que N horas, mantendo o registro "
        "(padrão: IMAGE_RETENTION_HOURS).\n"
        "  Use --images-only para purgar apenas imagens sem tocar nos registros."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=settings.EVENT_RETENTION_DAYS,
            help="Deleta registros PlateEvent mais antigos que N dias.",
        )
        parser.add_argument(
            "--image-hours",
            type=int,
            default=settings.IMAGE_RETENTION_HOURS,
            help="Deleta arquivos PNG mais antigos que N horas (mantém o registro).",
        )
        parser.add_argument(
            "--images-only",
            action="store_true",
            help="Purga apenas imagens, não deleta registros.",
        )
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        if not options["images_only"]:
            self._purge_records(options["days"], dry_run)

        self._purge_images(options["image_hours"], dry_run)

    def _purge_images(self, hours: int, dry_run: bool) -> None:
        cutoff = timezone.now() - timedelta(hours=hours)

        plate_qs = PlateEvent.objects.filter(captured_at__lt=cutoff).exclude(image="")
        access_qs = AccessEvent.objects.filter(captured_at__lt=cutoff).exclude(image="", crop_image="")

        if dry_run:
            self.stdout.write(
                f"[dry-run] {plate_qs.count()} PlateEvent com imagem | "
                f"{access_qs.count()} AccessEvent com imagem — seriam apagadas (cutoff: {cutoff})"
            )
            return

        plate_deleted = 0
        for ev in plate_qs.only("id", "image").iterator(chunk_size=500):
            if _delete_image_field(ev, "image"):
                plate_deleted += 1

        access_img = access_crop = 0
        for ev in access_qs.only("id", "image", "crop_image").iterator(chunk_size=500):
            if _delete_image_field(ev, "image"):
                access_img += 1
            if _delete_image_field(ev, "crop_image"):
                access_crop += 1

        self.stdout.write(self.style.SUCCESS(
            f"Imagens apagadas — PlateEvent: {plate_deleted} | "
            f"AccessEvent.image: {access_img} | AccessEvent.crop: {access_crop}"
        ))

    def _purge_records(self, days: int, dry_run: bool) -> None:
        cutoff = timezone.now() - timedelta(days=days)
        qs = PlateEvent.objects.filter(captured_at__lt=cutoff)
        count = qs.count()

        if dry_run:
            self.stdout.write(f"[dry-run] {count} registros PlateEvent seriam deletados (cutoff: {cutoff.date()})")
            return

        files_deleted = 0
        for ev in qs.exclude(image="").only("id", "image").iterator(chunk_size=500):
            if _delete_image_field(ev, "image"):
                files_deleted += 1

        qs.delete()
        self.stdout.write(self.style.SUCCESS(
            f"Registros deletados: {count} | Arquivos removidos: {files_deleted}"
        ))
