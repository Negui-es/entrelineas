import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from accounts.models import User
from library.document_import import import_manifest


class Command(BaseCommand):
    help = "Previsualiza o aplica un manifiesto revisado de lecturas del Word."

    def add_arguments(self, parser):
        parser.add_argument("manifest")
        parser.add_argument("--user-id", required=True, type=int)
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--report")

    def handle(self, *args, **options):
        try:
            manifest = json.loads(Path(options["manifest"]).read_text(encoding="utf-8"))
            user = User.objects.get(pk=options["user_id"])
            result = import_manifest(user, manifest, apply=options["apply"])
        except Exception as exc:
            raise CommandError(str(exc)) from exc
        report = {"applied": options["apply"], "user_id": user.pk, "results": result}
        if options["report"]:
            Path(options["report"]).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        from collections import Counter
        self.stdout.write(str(dict(Counter(r["action"] for r in result))))
