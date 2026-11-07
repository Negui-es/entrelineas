from django.db import migrations


def link_existing(apps, schema_editor):
    Work = apps.get_model("library", "Work")
    Edition = apps.get_model("library", "Edition")
    for name in ("Book", "WishItem"):
        Model = apps.get_model("library", name)
        for item in Model.objects.filter(catalog_edition__isnull=True).iterator():
            work = Work.objects.create(identity=f"legacy:{name}:{item.pk}", title=item.title, author=item.author)
            edition = Edition.objects.create(work=work, title=item.title, author=item.author,
                                             total_pages=getattr(item, "total_pages", None),
                                             field_sources={"title": "legacy", "author": "legacy"})
            item.catalog_edition_id = edition.pk
            item.save(update_fields=["catalog_edition"])


class Migration(migrations.Migration):
    dependencies = [("library", "0002_shared_catalog")]
    operations = [migrations.RunPython(link_existing, migrations.RunPython.noop)]
