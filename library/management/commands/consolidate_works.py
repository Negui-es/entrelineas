from django.core.management.base import BaseCommand
from django.db import transaction
from library.matching import same_work_confidence
from library.models import Work
from library.work_identity import work_data, merge_works


class Command(BaseCommand):
    help = "List conservative work matches; --apply consolidates them without deleting old IDs or reviews."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")

    @transaction.atomic
    def handle(self, *args, **options):
        clusters = []
        for work in Work.objects.filter(merged_into__isnull=True).exclude(origin="legacy").prefetch_related("editions").order_by("created_at", "pk"):
            head = work_data(work)
            members = [head, *[{**head, "title": e.title, "author": e.author} for e in work.editions.all()]]
            for cluster in clusters:
                if all(same_work_confidence(a, b)["automatic"] for a in members for unused, existing in cluster for b in existing):
                    cluster.append((work, members))
                    break
            else:
                clusters.append([(work, members)])
        groups = [cluster for cluster in clusters if len(cluster) > 1]
        self.stdout.write(f"Compatible groups: {len(groups)}")
        for cluster in groups:
            works = [work for work, unused in cluster]
            self.stdout.write(f"{works[0].pk}: {len(works)} works")
            if options["apply"]:
                merge_works(works)
