from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from plates.models import PlateEvent


class Command(BaseCommand):
    help = "Delete plate events older than EVENT_RETENTION_DAYS."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=settings.EVENT_RETENTION_DAYS)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=options["days"])
        queryset = PlateEvent.objects.filter(captured_at__lt=cutoff)
        count = queryset.count()

        if options["dry_run"]:
            self.stdout.write(f"{count} events would be deleted.")
            return

        queryset.delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {count} old events."))
