from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def link_reviews(apps, schema_editor):
    Review = apps.get_model("library", "Review")
    Work = apps.get_model("library", "Work")
    Edition = apps.get_model("library", "Edition")
    Book = apps.get_model("library", "Book")
    seen = set()
    for review in Review.objects.select_related("book__catalog_edition").order_by("-updated_at", "-pk"):
        book = review.book
        if not book.catalog_edition_id:
            work = Work.objects.create(identity=f"legacy:Book:{book.pk}", title=book.title, author=book.author, origin="legacy")
            book.catalog_edition = Edition.objects.create(work=work, title=book.title, author=book.author, origin="legacy", total_pages=book.total_pages)
            book.save(update_fields=["catalog_edition"])
        review.owner_id = book.owner_id
        review.work_id = book.catalog_edition.work_id
        key = (review.owner_id, review.work_id)
        review.is_current = key not in seen
        seen.add(key)
        review.save(update_fields=["owner", "work", "is_current"])
    for work in Work.objects.filter(identity__startswith="legacy:"):
        work.origin = "legacy"
        work.save(update_fields=["origin"])
        Edition.objects.filter(work=work).update(origin="legacy")


class Migration(migrations.Migration):
    dependencies = [("library", "0003_link_existing_books"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.AddField("work", "origin", models.CharField(max_length=12, default="external", choices=[("external", "external"), ("user", "user"), ("legacy", "legacy")])),
        migrations.AddField("work", "created_by", models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, related_name="created_works", on_delete=django.db.models.deletion.SET_NULL)),
        migrations.AddField("work", "verified", models.BooleanField(default=False)),
        migrations.AddField("work", "merged_into", models.ForeignKey("library.Work", null=True, blank=True, related_name="aliases", on_delete=django.db.models.deletion.PROTECT)),
        migrations.AddField("edition", "origin", models.CharField(max_length=12, default="external", choices=[("external", "external"), ("user", "user"), ("legacy", "legacy")])),
        migrations.AddField("edition", "created_by", models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, related_name="created_editions", on_delete=django.db.models.deletion.SET_NULL)),
        migrations.AddField("edition", "verified", models.BooleanField(default=False)),
        migrations.AddField("edition", "cover_image", models.ImageField(upload_to="covers/", blank=True)),
        migrations.AddField("review", "owner", models.ForeignKey(settings.AUTH_USER_MODEL, null=True, related_name="work_reviews", on_delete=django.db.models.deletion.CASCADE)),
        migrations.AddField("review", "work", models.ForeignKey("library.Work", null=True, blank=True, related_name="reviews", on_delete=django.db.models.deletion.PROTECT)),
        migrations.AddField("review", "is_current", models.BooleanField(default=True, editable=False)),
        migrations.RunPython(link_reviews, migrations.RunPython.noop),
        migrations.AlterField("review", "owner", models.ForeignKey(settings.AUTH_USER_MODEL, related_name="work_reviews", on_delete=django.db.models.deletion.CASCADE)),
        migrations.AddConstraint("review", models.UniqueConstraint(fields=["owner", "work"], condition=models.Q(is_current=True, work__isnull=False), name="one_current_review_per_work")),
    ]
