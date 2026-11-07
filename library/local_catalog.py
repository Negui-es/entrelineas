"""Bibliographic records contributed to Entrelíneas, without personal data."""
from django.conf import settings
from .catalog import canonical_isbn
from .models import Edition
from .ranking import normalize, rank_results
from .matching import group_works


def edition_data(edition):
    data = {field: getattr(edition, field) for field in ("title", "author", "isbn", "publisher", "publication_date", "language", "total_pages", "synopsis", "field_sources")}
    data.update(provider="local", kind="edition", source_id=str(edition.pk), local_id=str(edition.pk),
                work_key=str(edition.work_id), cover_url=edition.display_cover_url,
                cover_scope="edition" if edition.cover_image or edition.cover_url else "work", color="blue",
                sources=[{"provider": s.provider, "external_id": s.external_id, "url": s.url, "metadata": {}} for s in edition.sources.all()],
                conflicts=[], origin=edition.origin, verified=edition.verified, has_uploaded_cover=bool(edition.cover_image))
    return data


def supplement(results, query, mode, page):
    isbn = canonical_isbn(query)
    terms = normalize(query).split()
    found = []
    for edition in Edition.objects.exclude(origin="legacy").select_related("work").prefetch_related("sources").order_by("created_at", "pk").iterator(chunk_size=200):
        if isbn:
            matches = edition.isbn == isbn
        else:
            value = normalize(edition.author if mode == "author" else edition.title if mode == "title" else edition.title + " " + edition.author)
            matches = all(term in value for term in terms)
        if matches:
            found.append(edition_data(edition))
    local = found[(page-1)*20:page*20]
    raw = [member for item in results["items"] for member in item.get("editions", [item])]
    ordered = group_works(rank_results([*raw, *local], query, mode, settings.CATALOG_PREFERRED_LANGUAGE))
    return {**results, "items": ordered, "total": len(ordered), "has_next": results["has_next"] or len(found) > page*20,
            "unavailable": results.get("unavailable", False) and not local}
