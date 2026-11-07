from django.utils.translation import gettext_lazy as _
"""Persist bibliography without exposing or changing private readings."""
from django.db import transaction
from .models import CatalogSource, Edition, Work
from .catalog import CatalogError, canonical_isbn, safe_cover
from .work_identity import resolve_work

FIELDS = ("title", "author", "publisher", "publication_date", "language", "total_pages", "cover_url", "synopsis")


@transaction.atomic
def store_edition(data):
    if data.get("provider") == "local":
        edition = Edition.objects.filter(pk=data.get("local_id"), isbn=data.get("isbn") or None).first()
        if not edition:
            raise CatalogError(_("La edición ya no está disponible. Vuelve a buscarla."))
        return edition
    edition = None
    for source in data["sources"]:
        record = CatalogSource.objects.select_related("edition").filter(provider=source["provider"], external_id=source["external_id"]).first()
        if record:
            edition = record.edition
            break
    isbn = canonical_isbn(data.get("isbn", "")) or None
    if edition and isbn and edition.isbn and isbn != edition.isbn:
        raise CatalogError(_("La fuente ha cambiado el ISBN. No hemos modificado la edición guardada."))
    if not edition and isbn:
        edition = Edition.objects.filter(isbn=isbn).first()
    if not edition:
        work = resolve_work(data)
        values = {field: data.get(field) for field in FIELDS}
        values["cover_url"] = safe_cover(values.get("cover_url", ""))
        if isbn:
            edition, unused = Edition.objects.get_or_create(isbn=isbn, defaults={"work": work, "field_sources": data["field_sources"], **values})
        else:
            edition = Edition.objects.create(work=work, field_sources=data["field_sources"], **values)
    for source in data["sources"]:
        record, unused = CatalogSource.objects.get_or_create(provider=source["provider"], external_id=source["external_id"], defaults={"edition": edition, "url": source["url"], "metadata": source["metadata"]})
        if record.edition_id != edition.pk:
            raise CatalogError(_("Las fuentes no coinciden con la edición guardada. Selecciona el resultado por separado."))
    return edition
