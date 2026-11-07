"""Bounded CSV parsing and additive, private Goodreads imports. No network calls."""
import csv
import io
import re
from datetime import date
from html import unescape

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils.html import strip_tags
from django.utils.translation import gettext as _

from accounts.models import User
from .catalog import canonical_isbn, positive_int
from .models import Book, Edition, GoodreadsEntry, Review, Wishlist, WishItem
from .ranking import normalize
from .goodreads_catalog import prepare_rows, persist_match, link_existing
from .catalog import CatalogError

MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 5000


def parse_export(upload):
    raw = upload.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValidationError(_("El archivo supera el límite de 5 MB."))
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValidationError(_("El archivo debe ser el CSV original de Goodreads, con codificación UTF-8."))
    reader = csv.DictReader(io.StringIO(content, newline=""), strict=True)
    rows, issues, seen = [], [], set()
    try:
        if not {"Book Id", "Title", "Author", "My Rating", "My Review", "Exclusive Shelf"}.issubset(reader.fieldnames or []):
            raise ValidationError(_("No reconocemos este CSV. Descarga el archivo desde Export Library en Goodreads."))
        for number, source in enumerate(reader, 2):
            if number > MAX_ROWS + 1:
                raise ValidationError(_("Puedes importar hasta 5.000 libros por archivo."))
            if None in source or any(value is None for value in source.values()):
                raise ValidationError(_("El CSV contiene filas incompletas. Vuelve a descargar el archivo original."))
            row = {key: value.strip() for key, value in source.items()}
            title, author, external_id = row["Title"], row["Author"], row["Book Id"]
            if not title or not author or len(title) > 200 or len(author) > 160 or not re.fullmatch(r"[0-9]{1,40}", external_id):
                issues.append(_("Fila %(row)s: título, autor o identificador ausente o demasiado largo; se omite.") % {"row": number})
                continue
            if external_id in seen:
                issues.append(_("Fila %(row)s: identificador repetido; se omite.") % {"row": number})
                continue
            seen.add(external_id)
            rating = row["My Rating"]
            if rating and not re.fullmatch(r"[0-5](?:\.0+)?", rating):
                issues.append(_("Fila %(row)s: valoración inválida; se omite el libro.") % {"row": number})
                continue
            rating = int(rating.split(".")[0]) if rating else 0
            finished = None
            if row.get("Date Read"):
                try:
                    finished = date.fromisoformat(row["Date Read"].replace("/", "-")).isoformat()
                except ValueError:
                    issues.append(_("Fila %(row)s: fecha de fin inválida; se importa sin esa fecha.") % {"row": number})
            shelf = row["Exclusive Shelf"]
            status = {"read": Book.Status.FINISHED, "currently-reading": Book.Status.READING, "to-read": Book.Status.PENDING}.get(shelf, Book.Status.PENDING)
            if shelf not in {"read", "currently-reading", "to-read"}:
                issues.append(_("Fila %(row)s: estantería desconocida; se importa como Pendiente.") % {"row": number})
            isbn = ""
            for field in ("ISBN13", "ISBN"):
                candidate = row.get(field, "")
                if candidate.startswith('="') and candidate.endswith('"'):
                    candidate = candidate[2:-1]
                isbn = canonical_isbn(candidate)
                if isbn:
                    break
            # Goodreads exports HTML. Keep paragraph breaks, store plain text and
            # let Django escape it on output, including encoded markup.
            text = unescape(strip_tags(re.sub(r"(?i)<br\s*/?>|</p\s*>", "\n", row["My Review"]))).strip()
            destination = "wishlist" if shelf == "to-read" and not (text or rating or finished) else "library"
            rows.append({"external_id": external_id, "title": title, "author": author, "isbn": isbn,
                         "rating": rating or None, "text": text, "destination": destination,
                         "contains_spoilers": row.get("Spoiler", "").casefold() in {"true", "1", "yes"},
                         "publisher": row.get("Publisher", "")[:200],
                         "status": status, "finished_at": finished,
                         "total_pages": positive_int(row.get("Number of Pages"))})
    except (csv.Error, ValueError):
        raise ValidationError(_("No se ha podido leer el CSV. Utiliza el archivo original de Goodreads."))
    if not rows:
        raise ValidationError(_("No hay libros válidos para importar. Comprueba el archivo y los campos de título y autor."))
    return rows, issues


def find_book(row, books):
    if row["isbn"]:
        found = next((b for b in books if canonical_isbn(getattr(b.metadata, "isbn", "")) == row["isbn"]), None)
        if found:
            return found
    found = next((b for b in books if normalize(b.metadata.title) == normalize(row["title"])
                  and normalize(b.metadata.author) == normalize(row["author"])), None)
    if found:
        return found
    match = row.get("catalog_data")
    if match:
        return find_book({"isbn": match.get("isbn") or "", "title": match["title"], "author": match["author"]}, books)
    return None


def preview_rows(user, rows):
    books = list(Book.objects.filter(owner=user).select_related("catalog_edition__work"))
    wishes = list(WishItem.objects.filter(wishlist__owner=user).select_related("catalog_edition__work"))
    imported = set(GoodreadsEntry.objects.filter(owner=user).values_list("external_id", flat=True))
    result = []
    for row in rows:
        is_wish = row["destination"] == "wishlist"
        book = find_book(row, wishes if is_wish else books)
        if row["external_id"] in imported:
            action = _("Ya importado; completar ficha si falta")
        elif book:
            action = _("Deseo existente; conservar sus datos") if is_wish else _("Libro existente; conservar sus datos")
        else:
            action = _("Añadir a Deseos") if is_wish else _("Añadir libro")
        result.append({**row, "action": action, "status_label": Book.Status(row["status"]).label,
                       "destination_label": _("Lista de deseos") if is_wish else _("Biblioteca")})
    return result


@transaction.atomic
def import_rows(user, rows):
    # Serialise imports for this owner, including repeat submissions.
    User.objects.select_for_update().get(pk=user.pk)
    books = list(Book.objects.filter(owner=user).select_related("catalog_edition__work"))
    wishes = list(WishItem.objects.filter(wishlist__owner=user).select_related("catalog_edition__work"))
    imported = {entry.external_id: entry for entry in GoodreadsEntry.objects.filter(owner=user).select_related("book", "wish")}
    counts = {"books": 0, "wishes": 0, "reviews": 0, "skipped": 0, "kept_reviews": 0, "linked": 0}
    for row in rows:
        if "catalog_data" not in row:
            prepare_rows([row])
        try:
            with transaction.atomic():
                edition = persist_match(row)
        except (CatalogError, IntegrityError, ValueError):
            edition = None
        if row["external_id"] in imported:
            entry = imported[row["external_id"]]
            counts["linked"] += int(link_existing(entry.book or entry.wish, edition))
            counts["skipped"] += 1
            continue
        if row["destination"] == "wishlist":
            wish = find_book(row, wishes)
            if not wish:
                listing, _unused = Wishlist.objects.get_or_create(owner=user)
                wish = WishItem.objects.create(wishlist=listing, catalog_edition=edition,
                                               title=row["title"], author=row["author"])
                wishes.append(wish)
                counts["wishes"] += 1
                counts["linked"] += int(edition is not None)
            else:
                counts["linked"] += int(link_existing(wish, edition))
            entry = GoodreadsEntry.objects.create(owner=user, external_id=row["external_id"], wish=wish)
            imported[row["external_id"]] = entry
            continue
        book = find_book(row, books)
        if not book:
            pages = edition.total_pages if edition else row["total_pages"]
            book = Book.objects.create(owner=user, catalog_edition=edition, title=row["title"], author=row["author"],
                isbn=row["isbn"], total_pages=pages, status=row["status"], finished_at=row["finished_at"],
                current_page=(pages or 0) if row["status"] == Book.Status.FINISHED else 0)
            books.append(book)
            counts["books"] += 1
            counts["linked"] += int(edition is not None)
        else:
            counts["linked"] += int(link_existing(book, edition))
        if row["text"] or row["rating"]:
            existing = Review.objects.filter(book=book).exists() or (
                book.catalog_edition_id and Review.objects.filter(owner=user, work=book.catalog_edition.work, is_current=True).exists())
            if existing:
                counts["kept_reviews"] += 1
            else:
                Review.objects.create(book=book, owner=user, text=row["text"], rating=row["rating"],
                                      contains_spoilers=row["contains_spoilers"], is_draft=False)
                counts["reviews"] += 1
        entry = GoodreadsEntry.objects.create(owner=user, external_id=row["external_id"], book=book)
        imported[row["external_id"]] = entry
    return counts
