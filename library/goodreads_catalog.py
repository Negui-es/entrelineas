"""Bibliographic matching for imports, using the catalog's existing work guards."""
from django.utils.translation import gettext as _
from django.db import IntegrityError, transaction

from . import catalog
from .catalog_store import FIELDS, store_edition
from .local_catalog import edition_data
from .matching import same_work_confidence
from .models import Edition, Review
from .ranking import normalize
from .work_identity import align_review, merge_works


def compatible(row, item):
    return item.get("kind") == "edition" and same_work_confidence(row, item)["automatic"]


def choose(row, items):
    valid = [item for item in items if compatible(row, item)]
    if not valid:
        return None
    def key(item):
        return (-int(bool(row["isbn"] and catalog.canonical_isbn(item.get("isbn", "")) == row["isbn"])),
                -same_work_confidence(row, item)["score"], -int(bool(item.get("cover_url"))),
                -int(bool(row.get("publisher") and normalize(row["publisher"]) == normalize(item.get("publisher")))),
                str(item.get("provider", "")), str(item.get("source_id", "")))
    valid.sort(key=key)
    best = valid[0]
    # Near matches must not silently choose between incompatible titles.
    if any(key(item)[:2] == key(best)[:2] and not same_work_confidence(best, item)["automatic"] for item in valid[1:]):
        return None
    return best


def set_match(row, data, fallback=None):
    row["catalog_data"] = data
    row["catalog_fallback"] = fallback
    row["match_cover"] = (data or {}).get("cover_url", "") or (fallback or {}).get("cover_url", "")
    if not data:
        row["match_label"] = _("Sin coincidencia fiable; se conservarán los datos del CSV")
    elif row["isbn"] and catalog.canonical_isbn(data.get("isbn", "")) == row["isbn"]:
        row["match_label"] = _("Edición encontrada por ISBN")
    elif row["isbn"] and data.get("isbn"):
        row["match_label"] = _("Misma obra; otra edición")
    else:
        row["match_label"] = _("Coincidencia por título y autor")
    row["match_title"] = (data or {}).get("title", "")
    row["match_author"] = (data or {}).get("author", "")
    row["match_isbn"] = (data or {}).get("isbn") or ""
    row["match_cover_from_work"] = bool(fallback or (data or {}).get("cover_scope") == "work")
    return row


def prepare_rows(rows):
    editions = list(Edition.objects.exclude(origin="legacy").select_related("work").prefetch_related("sources"))
    items = [edition_data(edition) for edition in editions]
    for row in rows:
        primary = choose(row, items)
        fallback = choose(row, [item for item in items if item.get("cover_url") and primary and same_work_confidence(primary, item)["automatic"]]) if primary and not primary.get("cover_url") else None
        set_match(row, primary, fallback)
        if not primary:
            row["match_label"] = _("Pendiente de buscar en las fuentes externas")
    return rows


def flatten(results):
    return [edition for item in results.get("items", []) for edition in item.get("editions", [item])]


def match_remote(row):
    """Only send ISBN/title/author, never a user's reviews or reading history."""
    candidates = [row["catalog_data"]] if row.get("catalog_data") else []
    if candidates and row.get("match_cover"):
        return row
    if row["isbn"]:
        candidates.extend(flatten(catalog.search(row["isbn"], "isbn")))
    primary = choose(row, candidates)
    title_searched = False
    if not primary or not primary.get("cover_url"):
        query = (row["title"] + " " + row["author"])[:160]
        candidates.extend(flatten(catalog.search(query, "all")))
        title_searched = True
        primary = choose(row, candidates)
    if not primary:
        return set_match(row, None)

    def details(item):
        data = item if item.get("provider") == "local" else catalog.details({**item, "alternatives": item.get("alternatives", [])[:1]})
        return data if compatible(row, data) else None

    data = details(primary)
    if not data:
        return set_match(row, None)
    fallback = None
    if not data.get("cover_url"):
        if not title_searched:
            candidates.extend(flatten(catalog.search((row["title"] + " " + row["author"])[:160], "all")))
        cover_candidates = [item for item in candidates if item.get("cover_url") and compatible(row, item)
                            and (item.get("provider"), item.get("source_id")) != (primary.get("provider"), primary.get("source_id"))
                            and same_work_confidence(data, item)["automatic"]]
        for candidate in cover_candidates[:2]:
            try:
                alternative = details(candidate)
            except catalog.CatalogError:
                continue
            if alternative and alternative.get("cover_url") and same_work_confidence(data, alternative)["automatic"]:
                fallback = alternative
                break
    return set_match(row, data, fallback)


def persist_match(row):
    data = row.get("catalog_data")
    if not data or not compatible(row, data):
        return None

    def store(data):
        edition = store_edition(data)
        if not compatible(row, edition_data(edition)):
            raise catalog.CatalogError("Contradictory catalog metadata")
        # Existing editions keep their values; fill only missing catalog fields.
        if data.get("provider") != "local":
            edition = Edition.objects.select_for_update().get(pk=edition.pk)
            changed = []
            for field in FIELDS:
                if not getattr(edition, field) and data.get(field) and not (field == "cover_url" and edition.cover_image):
                    setattr(edition, field, data[field])
                    edition.field_sources[field] = data.get("field_sources", {}).get(field, data["provider"])
                    changed.append(field)
            if changed:
                edition.save(update_fields=[*changed, "field_sources"])
        return edition

    edition = store(data)
    fallback = row.get("catalog_fallback")
    if fallback and compatible(row, fallback) and same_work_confidence(data, fallback)["automatic"]:
        try:
            with transaction.atomic():
                other = store(fallback)
                if edition.work_id != other.work_id:
                    merge_works([edition.work, other.work])
                    edition.refresh_from_db()
        except (catalog.CatalogError, IntegrityError, ValueError):
            pass  # A failed cover fallback must not discard the exact edition.
    return edition


def link_existing(item, edition):
    if not edition or item.catalog_edition_id:
        return False
    if hasattr(item, "current_page") and edition.total_pages and item.current_page > edition.total_pages:
        return False
    item.catalog_edition = edition
    item.save(update_fields=["catalog_edition"])
    if hasattr(item, "current_page"):
        previous = Review.objects.filter(owner=item.owner, work=edition.work, is_current=True).exclude(book=item).first()
        if previous:
            # Keep both reviews, with the existing work review still current.
            Review.objects.filter(book=item).update(work=edition.work, is_current=False)
        else:
            align_review(item)
    return True
