from django.conf import settings
from django.core.management import BaseCommand, call_command


class Command(BaseCommand):
    help = "Run the development server with Celery tasks executed inline when DEBUG is true."

    def add_arguments(self, parser):
        parser.add_argument(
            "addrport",
            nargs="?",
            default="127.0.0.1:8000",
            help="Optional port number, or ipaddr:port.",
        )
        parser.add_argument(
            "--noreload",
            action="store_true",
            help="Do not use the auto-reloader.",
        )

    def handle(self, *args, **options):
        if settings.CELERY_TASK_ALWAYS_EAGER:
            self.stdout.write(
                self.style.SUCCESS(
                    "Dev Celery enabled: tasks run inline in this runserver process.",
                )
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    "Celery eager mode is disabled; a separate worker/broker is required.",
                )
            )

        if settings.DEBUG and not settings.USE_REDIS_IN_DEBUG:
            self.stdout.write("Dev cache enabled: using local memory instead of Redis.")

        call_command(
            "runserver",
            options["addrport"],
            use_reloader=not options["noreload"],
        )
