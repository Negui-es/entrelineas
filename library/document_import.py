"""Import a reviewed document manifest, preserving existing personal reviews."""
from datetime import date
from decimal import Decimal
import re

from django.core.exceptions import ValidationError
from django.db import transaction

from accounts.models import User
from .models import Book, DocumentImportEntry, Review
from .ranking import normalize


def merged_text(existing, incoming):
    """Keep edited prose; retain distinct source versions without repeating exact text."""
    if not incoming.strip():
        return existing
    if not existing.strip():
        return incoming
    compact = lambda s: re.sub(r"\s+", " ", s).strip()
    if compact(incoming) in compact(existing):
        return existing
    return existing + "\n\n— Notas del Word —\n\n" + incoming


@transaction.atomic
def import_manifest(user, manifest, *, apply=False):
    User.objects.select_for_update().get(pk=user.pk)
    if manifest["owner_id"] != user.pk:
        raise ValidationError("El manifiesto pertenece a otro usuario.")
    rows = manifest["books"]
    if len({r["source_key"] for r in rows}) != len(rows):
        raise ValidationError("Identificadores de origen repetidos.")
    if manifest["existing_rating_policy"] != "keep_web":
        raise ValidationError("Este importador conserva las valoraciones existentes.")
    existing = list(Book.objects.filter(owner=user).select_related("catalog_edition__work"))
    imported = set(DocumentImportEntry.objects.filter(owner=user).values_list("source_key", flat=True))
    result = []
    for row in rows:
        if row["source_key"] in imported:
            result.append({"title": row["title"], "action": "already_imported"})
            continue
        if row.get("existing_book_id"):
            book = next((b for b in existing if b.pk == row["existing_book_id"]), None)
            if (not book or normalize(book.author) != normalize(row["author"])
                    or normalize(re.sub(r"\s*\(.*?\)", "", book.title)) != normalize(row["title"])):
                raise ValidationError("La lectura existente no coincide con el propietario o autor.")
        else:
            matches = [b for b in existing if normalize(b.metadata.title) == normalize(row["title"])
                       and normalize(b.metadata.author) == normalize(row["author"])]
            if len(matches) > 1:
                raise ValidationError("Hay varias lecturas posibles para " + row["title"])
            book = matches[0] if matches else None
        review = book.work_review if book else None
        rating = Decimal(row["rating"]) if row["rating"] is not None else None
        if review and review.rating is not None:
            rating = review.rating
        text = merged_text(review.text if review else "", row["text"])
        create_review = bool(review or text or rating is not None)
        details = {"title": row["title"], "action": "update" if book else "create",
                   "book_id": book.pk if book else None, "rating": str(rating) if rating is not None else None,
                   "review": create_review}
        started = date.fromisoformat(row["started_at"])
        finished = date.fromisoformat(row["finished_at"]) if row["finished_at"] else None
        candidate = book or Book(owner=user, title=row["title"], author=row["author"])
        candidate.status = row["status"]
        candidate.started_at = started
        candidate.finished_at = finished
        candidate.full_clean()
        if create_review:
            # A temporary unsaved Book still needs a PK for field validation.
            check = Review(book=book or candidate, owner=user, rating=rating, text=text)
            check.clean_fields(exclude=["book"])
        if apply:
            candidate.save()
            if create_review:
                review = review or Review(book=candidate, owner=user)
                review.text = text
                review.rating = rating
                review.contains_spoilers = review.contains_spoilers or row["contains_spoilers"]
                review.is_draft = not bool(text.strip())
                review.full_clean()
                review.save()
            DocumentImportEntry.objects.create(owner=user, book=candidate, source_key=row["source_key"], payload=row)
            details["book_id"] = candidate.pk
        result.append(details)
    return result
