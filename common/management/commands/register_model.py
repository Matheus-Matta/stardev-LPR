import hashlib
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from common.mlops import promote_model
from common.models import AIModelArtifact


class Command(BaseCommand):
    help = "Register a versioned AI model artifact and optionally promote it."

    def add_arguments(self, parser):
        parser.add_argument("--kind", choices=AIModelArtifact.Kind.values, required=True)
        parser.add_argument("--model-version", required=True)
        parser.add_argument("--uri", required=True)
        parser.add_argument("--sha256", default="")
        parser.add_argument("--promote", action="store_true")
        parser.add_argument("--notes", default="")

    def handle(self, *args, **options):
        sha256 = options["sha256"]
        uri = options["uri"]
        path = Path(uri)
        if not sha256 and path.exists() and path.is_file():
            sha256 = _sha256_file(path)

        artifact, created = AIModelArtifact.objects.update_or_create(
            kind=options["kind"],
            version=options["model_version"],
            defaults={
                "storage_uri": uri,
                "file_sha256": sha256,
                "notes": options["notes"],
            },
        )
        if options["promote"]:
            promote_model(artifact)

        verb = "Created" if created else "Updated"
        self.stdout.write(self.style.SUCCESS(f"{verb} {artifact}"))


def _sha256_file(path: Path) -> str:
    if not path.exists():
        raise CommandError(f"Model file not found: {path}")

    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"
