"""Versioned Entrelíneas CSV: private, additive and lossless for personal text."""
import csv
import hashlib
import io
import json
import re
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.translation import gettext as _

from accounts.models import User
from .catalog import canonical_isbn, safe_cover
from .models import Book, CSVImportEntry, DocumentImportEntry, Edition, ReadingNote, Review, Wishlist, WishItem, Work
from .ranking import normalize

MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 5000
csv.field_size_limit(MAX_BYTES)
REVIEW_FIELDS = ("rating", "text", "best", "worst", "memory", "recommended_for", "tags",
                 "contains_spoilers", "favorite", "is_draft", "is_current", "created_at", "updated_at")
FIELDS = ("format", "version", "type", "id", "title", "author", "isbn", "status", "color",
          "total_pages", "current_page", "started_at", "finished_at", "created_at", "updated_at",
          "work_id", "publisher", "publication_date", "language", "synopsis", "cover_url",
          "review_present", *["review_" + f for f in REVIEW_FIELDS], "notes", "document_sources",
          "wish_edition", "wish_purchase_url", "wish_priority")


def excel_safe(value):
    value = "" if value is None else str(value)
    # Escaping initial apostrophes makes this reversible even for literal '= text.
    return "'" + value if value.startswith(("'", "\t", "\r")) or re.match(r"^\s*[=+@-]", value) else value


def excel_unescape(value):
    if value.startswith("'") and excel_safe(value[1:]) == value:
        return value[1:]
    return value


def identity_map(entries):
    result = {}
    for entry in entries:
        result.setdefault(("book", entry.book_id) if entry.book_id else ("wish", entry.wish_id), str(entry.source_id))
    return result


def source_id(user, obj, kind, identities):
    if (kind, obj.pk) in identities:
        return identities[(kind, obj.pk)]
    namespace = uuid.UUID(hashlib.sha256(settings.SECRET_KEY.encode()).hexdigest()[:32])
    return str(uuid.uuid5(namespace, f"{user.pk}:{kind}:{obj.pk}"))


def export_csv(user):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=FIELDS)
    writer.writeheader()
    identities = identity_map(CSVImportEntry.objects.filter(owner=user).order_by("pk"))
    books = Book.objects.filter(owner=user).select_related("catalog_edition__work", "review").prefetch_related("notes", "document_imports").order_by("pk")
    wishes = WishItem.objects.filter(wishlist__owner=user).select_related("catalog_edition__work").order_by("pk")
    for kind, objects in (("book", books), ("wish", wishes)):
        for obj in objects:
            meta = obj.metadata
            edition = obj.catalog_edition
            row = dict(format="entrelineas", version="1", type=kind, id=source_id(user, obj, kind, identities),
                       title=meta.title, author=meta.author, isbn=getattr(meta, "isbn", ""), color=obj.color,
                       total_pages=getattr(meta, "total_pages", None), created_at=obj.created_at.isoformat())
            if edition:
                row.update(work_id=str(edition.work_id), **{f: getattr(edition, f) for f in
                           ("publisher", "publication_date", "language", "synopsis", "cover_url")})
            if kind == "book":
                row.update(status=obj.status, current_page=obj.current_page,
                           started_at=obj.started_at.isoformat() if obj.started_at else "",
                           finished_at=obj.finished_at.isoformat() if obj.finished_at else "",
                           updated_at=obj.updated_at.isoformat(),
                           notes=json.dumps([dict(text=n.text, page=n.page, created_at=n.created_at.isoformat())
                                             for n in obj.notes.all()], ensure_ascii=False),
                           document_sources=json.dumps([dict(source_key=d.source_key, payload=d.payload)
                                                       for d in obj.document_imports.all()], ensure_ascii=False))
                # Export each actual review once, including historical versions;
                # work-level sharing is rebuilt through work_id on import.
                review = getattr(obj, "review", None)
                row["review_present"] = "true" if review else "false"
                if review:
                    for field in REVIEW_FIELDS:
                        value = getattr(review, field)
                        row["review_" + field] = value.isoformat() if hasattr(value, "isoformat") else (
                            str(value).lower() if isinstance(value, bool) else value)
            else:
                row.update(wish_edition=obj.edition, wish_purchase_url=obj.purchase_url, wish_priority=obj.priority)
            writer.writerow({key: excel_safe(value) for key, value in row.items()})
    return output.getvalue().encode("utf-8-sig")


def integer(value, *, optional=False):
    if optional and value == "":
        return None
    if not re.fullmatch(r"\d{1,10}", value) or int(value) > 2_147_483_647:
        raise ValueError("integer")
    return int(value)


def timestamp(value):
    if not value:
        return None
    result = parse_datetime(value)
    if result is None or timezone.is_naive(result):
        raise ValueError("timestamp")
    return result.isoformat()


def boolean(value):
    if value not in ("true", "false"):
        raise ValueError("boolean")
    return value == "true"


def parse_csv(upload):
    raw = upload.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValidationError(_("El archivo supera el límite de 5 MB."))
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""), strict=True)
        if reader.fieldnames != list(FIELDS):
            raise ValidationError(_("No reconocemos este CSV de Entrelíneas. Utiliza el archivo descargado con Exportar."))
        rows, seen = [], set()
        for number, source in enumerate(reader, 2):
            if number > MAX_ROWS + 1:
                raise ValidationError(_("Puedes importar hasta 5.000 libros por archivo."))
            try:
                if None in source or None in source.values():
                    raise ValueError("columns")
                row = {key: excel_unescape(value) for key, value in source.items()}
                if row["format"] != "entrelineas" or row["version"] != "1" or row["type"] not in ("book", "wish"):
                    raise ValueError("format/version/type")
                row["id"] = str(uuid.UUID(row["id"]))
                if row["id"] in seen:
                    raise ValueError("duplicate id")
                seen.add(row["id"])
                for field, limit in (("title", 200), ("author", 160), ("publisher", 200), ("language", 40),
                                     ("publication_date", 80), ("wish_edition", 160), ("wish_purchase_url", 200)):
                    if len(row[field]) > limit or (field == "title" and not row[field].strip()):
                        raise ValueError(field)
                row["total_pages"] = integer(row["total_pages"], optional=True)
                if row["total_pages"] == 0 or row["color"] not in Book.Color.values:
                    raise ValueError("pages/color")
                if row["isbn"] and not canonical_isbn(row["isbn"]):
                    raise ValueError("isbn")
                row["created_at"] = timestamp(row["created_at"])
                row["updated_at"] = timestamp(row["updated_at"])
                if row["work_id"]:
                    row["work_id"] = str(uuid.UUID(row["work_id"]))
                if row["type"] == "book":
                    row["current_page"] = integer(row["current_page"])
                    row["started_at"] = date.fromisoformat(row["started_at"]).isoformat() if row["started_at"] else None
                    row["finished_at"] = date.fromisoformat(row["finished_at"]).isoformat() if row["finished_at"] else None
                    if (row["status"] not in Book.Status.values or
                            (row["total_pages"] is not None and row["current_page"] > row["total_pages"]) or
                            (row["started_at"] and row["finished_at"] and row["finished_at"] < row["started_at"])):
                        raise ValueError("reading")
                    row["review_present"] = boolean(row["review_present"])
                    rating = Decimal(row["review_rating"]) if row["review_rating"] else None
                    if rating is not None and (not rating.is_finite() or not Decimal("0.5") <= rating <= 5
                                               or rating != rating.quantize(Decimal(".01"))):
                        raise ValueError("rating")
                    row["review_rating"] = str(rating) if rating is not None else None
                    for field in ("contains_spoilers", "favorite", "is_draft", "is_current"):
                        row["review_" + field] = boolean(row["review_" + field]) if row["review_present"] else False
                    for field in ("created_at", "updated_at"):
                        row["review_" + field] = timestamp(row["review_" + field])
                    if len(row["review_recommended_for"]) > 240 or len(row["review_tags"]) > 200:
                        raise ValueError("review")
                    row["notes"] = json.loads(row["notes"])
                    row["document_sources"] = json.loads(row["document_sources"])
                    if not isinstance(row["notes"], list) or not isinstance(row["document_sources"], list):
                        raise ValueError("notes")
                    for note in row["notes"]:
                        if not isinstance(note, dict) or not isinstance(note.get("text"), str):
                            raise ValueError("note")
                        if note.get("page") is not None:
                            note["page"] = integer(str(note["page"]))
                            if row["total_pages"] and note["page"] > row["total_pages"]:
                                raise ValueError("note page")
                        note["created_at"] = timestamp(note.get("created_at", ""))
                    for item in row["document_sources"]:
                        if not isinstance(item, dict) or not isinstance(item.get("payload"), dict) or not isinstance(item.get("source_key"), str):
                            raise ValueError("source")
                else:
                    if row["wish_priority"] not in ("high", "normal", "low"):
                        raise ValueError("priority")
                    if row["wish_purchase_url"]:
                        URLValidator(schemes=["http", "https"])(row["wish_purchase_url"])
                row.update(external_id=row["id"], destination="library" if row["type"] == "book" else "wishlist",
                           rating=row["review_rating"] if row["type"] == "book" else None,
                           text=row["review_text"] if row["type"] == "book" else "")
                rows.append(row)
            except (ValueError, TypeError, KeyError, InvalidOperation, ValidationError, OverflowError, RecursionError):
                raise ValidationError(_("Fila %(row)s: contiene datos inválidos. No se ha importado ningún dato.") % {"row": number})
    except (UnicodeDecodeError, csv.Error):
        raise ValidationError(_("No se ha podido leer el CSV. Utiliza un archivo UTF-8 exportado desde Entrelíneas."))
    if not rows:
        raise ValidationError(_("No hay libros válidos para importar. Comprueba el archivo y los campos de título y autor."))
    return rows, []


def exact_match(row, objects):
    matches = [obj for obj in objects if normalize(obj.metadata.title) == normalize(row["title"])
               and normalize(obj.metadata.author) == normalize(row["author"])
               and (not row["isbn"] or canonical_isbn(getattr(obj.metadata, "isbn", "")) == canonical_isbn(row["isbn"]))]
    return matches[0] if len(matches) == 1 else None


def preview_rows(user, rows):
    books = list(Book.objects.filter(owner=user).select_related("catalog_edition"))
    wishes = list(WishItem.objects.filter(wishlist__owner=user).select_related("catalog_edition"))
    imported = set(CSVImportEntry.objects.filter(owner=user).values_list("source_id", flat=True))
    result = []
    for row in rows:
        found = exact_match(row, books if row["type"] == "book" else wishes)
        action = _("Ya importado; conservar sus datos") if uuid.UUID(row["id"]) in imported else (
            _("Existente; completar datos que falten") if found else _("Añadir libro") if row["type"] == "book" else _("Añadir a Deseos"))
        result.append({**row, "action": action,
                       "status_label": Book.Status(row["status"]).label if row["type"] == "book" else "",
                       "destination_label": _("Biblioteca") if row["type"] == "book" else _("Lista de deseos")})
    return result


def restore_times(model, obj, values, fields=("created_at", "updated_at")):
    changes = {f: values[f] for f in fields if values.get(f)}
    if changes:
        model.objects.filter(pk=obj.pk).update(**changes)


def local_edition(row, user, work_groups):
    """Never modify a shared edition or fetch links supplied in a CSV."""
    if not row["work_id"] and not any(row[f] for f in ("publisher", "publication_date", "language", "synopsis", "cover_url")):
        return None
    isbn = canonical_isbn(row["isbn"]) or None
    if isbn:
        edition = Edition.objects.select_related("work").filter(isbn=isbn).first()
        if edition:
            return edition if normalize(edition.title) == normalize(row["title"]) and normalize(edition.author) == normalize(row["author"]) else None
    key = (row["work_id"] or row["id"], normalize(row["title"]), normalize(row["author"]))
    if key not in work_groups:
        work_groups[key] = Work.objects.create(identity="csv:" + uuid.uuid4().hex, title=row["title"], author=row["author"], origin="user", created_by=user)
    return Edition.objects.create(work=work_groups[key], title=row["title"], author=row["author"], isbn=isbn,
        publisher=row["publisher"], publication_date=row["publication_date"], language=row["language"],
        synopsis=row["synopsis"], cover_url=safe_cover(row["cover_url"]), total_pages=row["total_pages"],
        origin="user", created_by=user, field_sources={"import": "entrelineas_csv_v1"})


@transaction.atomic
def import_rows(user, rows):
    User.objects.select_for_update().get(pk=user.pk)
    books = list(Book.objects.filter(owner=user).select_related("catalog_edition__work"))
    wishes = list(WishItem.objects.filter(wishlist__owner=user).select_related("catalog_edition__work"))
    entries = list(CSVImportEntry.objects.filter(owner=user).order_by("pk"))
    imported = {str(e.source_id): e for e in entries}
    identities = identity_map(entries)
    originals = {source_id(user, item, kind, identities): item
                 for kind, pool in (("book", books), ("wish", wishes)) for item in pool}
    counts = dict(books=0, wishes=0, reviews=0, skipped=0, kept_reviews=0, linked=0, notes=0)
    work_groups = {}
    matched = set()
    # Current reviews precede older versions so no historical version replaces one.
    for row in sorted(rows, key=lambda r: not r.get("review_is_current", False)):
        if row["id"] in imported:
            counts["skipped"] += 1
            continue
        kind = row["type"]
        pool = books if kind == "book" else wishes
        obj = originals.get(row["id"])
        if obj is not None and ((kind == "book") != isinstance(obj, Book)):
            raise ValidationError(_("El identificador del archivo no coincide con el tipo de registro."))
        obj = obj or exact_match(row, [item for item in pool if (kind, item.pk) not in matched])
        if obj:
            matched.add((kind, obj.pk))
        new = obj is None
        if new:
            edition = local_edition(row, user, work_groups)
            shared = dict(title=row["title"], author=row["author"], catalog_edition=edition, color=row["color"])
            if kind == "book":
                obj = Book.objects.create(owner=user, isbn=row["isbn"], total_pages=row["total_pages"],
                    status=row["status"], current_page=row["current_page"], started_at=row["started_at"], finished_at=row["finished_at"], **shared)
                restore_times(Book, obj, row)
                counts["books"] += 1
            else:
                wishlist, unused = Wishlist.objects.get_or_create(owner=user)
                obj = WishItem.objects.create(wishlist=wishlist, edition=row["wish_edition"], purchase_url=row["wish_purchase_url"], priority=row["wish_priority"], **shared)
                restore_times(WishItem, obj, row, ("created_at",))
                counts["wishes"] += 1
            counts["linked"] += int(edition is not None)
        if kind == "book":
            if row["review_present"]:
                # Preserve existing reviews, including the current work-level one.
                existing = getattr(obj, "review", None) or (obj.work_review if row["review_is_current"] else None)
                if existing:
                    counts["kept_reviews"] += 1
                    changed = []
                    for field in ("rating", "text", "best", "worst", "memory", "recommended_for", "tags"):
                        if getattr(existing, field) in (None, "") and row["review_" + field] not in (None, ""):
                            setattr(existing, field, row["review_" + field])
                            changed.append(field)
                    if changed:
                        existing.save(update_fields=[*changed, "updated_at"])
                else:
                    values = {f: row["review_" + f] for f in REVIEW_FIELDS if f not in ("created_at", "updated_at")}
                    review = Review.objects.create(book=obj, owner=user, **values)
                    restore_times(Review, review, {f: row["review_" + f] for f in ("created_at", "updated_at")})
                    counts["reviews"] += 1
            for note in row["notes"]:
                if not obj.notes.filter(text=note["text"], page=note.get("page"), created_at=note["created_at"]).exists():
                    added = ReadingNote.objects.create(book=obj, text=note["text"], page=note.get("page"))
                    restore_times(ReadingNote, added, note, ("created_at",))
                    counts["notes"] += 1
            for index, item in enumerate(row["document_sources"]):
                DocumentImportEntry.objects.get_or_create(owner=user, book=obj, source_key=f"csv:{row['id']}:{index}", defaults={"payload": item["payload"]})
        entry = CSVImportEntry.objects.create(owner=user, source_id=row["id"], **{"book" if kind == "book" else "wish": obj})
        imported[row["id"]] = entry
    return counts
