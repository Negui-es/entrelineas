import csv
import io
import json
import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import translation

from . import native_csv
from .models import Book, CSVImportEntry, DocumentImportEntry, Edition, ReadingNote, Review, Wishlist, WishItem, Work
from .tests import AppTestCase


def upload(raw):
    return SimpleUploadedFile("entrelineas.csv", raw, content_type="text/csv")


def modified(raw, **changes):
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    rows[0].update(changes)
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=native_csv.FIELDS)
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8-sig")


@override_settings(SECURE_SSL_REDIRECT=False)
class NativeCSVTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.user = self.make_user()
        self.other = self.make_user("other@example.com")
        self.client.force_login(self.user)
        self.book = Book.objects.create(owner=self.user, title='=Título, "citado"', author="Autora Álvarez",
            status="abandoned", started_at=date(2024, 1, 1), total_pages=200, current_page=76, color="rose")
        self.review = Review.objects.create(book=self.book, rating=Decimal("4.25"),
            text="Primera línea\n\nSegunda, con comas", best="=1+1", worst="'literal", memory="@recuerdo",
            recommended_for="Amigas", tags="releer, breve", favorite=True, contains_spoilers=True, is_draft=False)
        ReadingNote.objects.create(book=self.book, page=20, text="Nota\npersonal")
        DocumentImportEntry.objects.create(owner=self.user, book=self.book, source_key="word:1", payload={"months": [1, 2]})
        listing = Wishlist.objects.create(owner=self.user)
        WishItem.objects.create(wishlist=listing, title="Deseado", author="Otra autora", priority="high",
                                purchase_url="https://example.org/libro", edition="Bolsillo", color="green")
        self.url = reverse("library_import")

    def test_full_roundtrip_and_repeat(self):
        raw = native_csv.export_csv(self.user)
        rows, issues = native_csv.parse_csv(upload(raw))
        self.assertEqual(issues, [])
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["title"], self.book.title)
        self.assertEqual(rows[0]["review_best"], "=1+1")
        result = native_csv.import_rows(self.other, rows)
        self.assertEqual((result["books"], result["reviews"], result["wishes"], result["notes"]), (1, 1, 1, 1))
        book = Book.objects.get(owner=self.other)
        review = Review.objects.get(owner=self.other)
        self.assertEqual(book.status, "abandoned")
        self.assertEqual(book.current_page, 76)
        self.assertEqual(book.started_at, self.book.started_at)
        self.assertIsNone(book.finished_at)
        self.assertEqual(book.created_at, self.book.created_at)
        for field in native_csv.REVIEW_FIELDS:
            self.assertEqual(getattr(review, field), getattr(self.review, field), field)
        note = book.notes.get()
        self.assertEqual(note.created_at, self.book.notes.get().created_at)
        self.assertEqual(note.text, "Nota\npersonal")
        wish = WishItem.objects.get(wishlist__owner=self.other)
        self.assertEqual((wish.priority, wish.edition, wish.purchase_url), ("high", "Bolsillo", "https://example.org/libro"))
        self.assertEqual(book.document_imports.get().payload, {"months": [1, 2]})
        self.assertEqual(native_csv.import_rows(self.other, rows)["skipped"], 2)
        self.assertEqual(book.notes.count(), 1)
        # Re-exporting the restored library keeps the portable IDs.
        restored, _ = native_csv.parse_csv(upload(native_csv.export_csv(self.other)))
        self.assertEqual({r["id"] for r in rows}, {r["id"] for r in restored})

    def test_preview_requires_confirmation_and_has_no_external_search(self):
        raw = native_csv.export_csv(self.user)
        self.client.force_login(self.other)
        with patch("library.goodreads_views.prepare_rows") as prepare, patch("library.goodreads_views.match_remote") as remote:
            response = self.client.post(self.url, {"source": "entrelineas", "file": upload(raw)})
            self.assertContains(response, "Confirmar importación")
            self.assertNotContains(response, 'src="/static/goodreads')
            self.assertEqual(Book.objects.filter(owner=self.other).count(), 0)
            token = response.context["token"]
            wrong = self.client.post(self.url, {"action": "match", "index": "0", "token": token})
            self.assertEqual(wrong.status_code, 400)
            result = self.client.post(self.url, {"action": "confirm", "token": token, "source": "goodreads"})
            self.assertEqual(result.context["result"]["books"], 1)
            prepare.assert_not_called()
            remote.assert_not_called()
        self.assertContains(self.client.post(self.url, {"action": "confirm", "token": token}), "caducado")

    def test_export_is_private_and_complete_not_filtered(self):
        response = self.client.get(reverse("library_export"), {"q": "no-match"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertIn("no-store", response["Cache-Control"])
        self.assertTrue(response.content.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"lector@example.com", response.content)
        self.assertEqual(len(native_csv.parse_csv(upload(response.content))[0]), 2)
        self.client.force_login(self.other)
        empty = self.client.get(reverse("library_export"))
        self.assertNotIn("Autora Álvarez", empty.content.decode("utf-8-sig"))
        self.assertEqual(Client().get(reverse("library_export")).status_code, 302)
        unverified = self.make_user("unverified@example.com", verified=False)
        self.client.force_login(unverified)
        self.assertTemplateUsed(self.client.get(reverse("library_export")), "account/verified_email_required.html")

    def test_existing_content_is_preserved_and_missing_review_fields_are_filled(self):
        rows, _ = native_csv.parse_csv(upload(native_csv.export_csv(self.user)))
        book = Book.objects.create(owner=self.other, title=self.book.title, author=self.book.author, status="reading")
        review = Review.objects.create(book=book, text="Mi texto", rating=2)
        result = native_csv.import_rows(self.other, rows)
        self.assertEqual(result["books"], 0)
        review.refresh_from_db(); book.refresh_from_db()
        self.assertEqual(review.text, "Mi texto")
        self.assertEqual(review.rating, 2)
        self.assertEqual(review.best, "=1+1")
        self.assertEqual(book.status, "reading")

    def test_invalid_files_are_rejected_before_any_write(self):
        raw = native_csv.export_csv(self.user)
        for change in ({"version": "99"}, {"current_page": "201"}, {"review_rating": "NaN"},
                       {"review_rating": "4.251"}, {"started_at": "mañana"}, {"notes": "{}"},
                       {"review_present": "yes"}, {"id": "bad"}, {"isbn": "bad"}):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                native_csv.parse_csv(upload(modified(raw, **change)))
        self.assertFalse(Book.objects.filter(owner=self.other).exists())
        for bad in (b"\xff", raw[:300], b"x" * (native_csv.MAX_BYTES + 1)):
            with self.assertRaises(ValidationError):
                native_csv.parse_csv(upload(bad))

    def test_formula_escape_is_safe_and_reversible(self):
        for value in ("=1+1", " +SUM(A1)", "-1", "@algo", "\ttexto", "\rtexto", "'literal", "'=literal", "normal"):
            encoded = native_csv.excel_safe(value)
            self.assertEqual(native_csv.excel_unescape(encoded), value)
            if value != "normal":
                self.assertTrue(encoded.startswith("'"))

    def test_legacy_wish_with_missing_author_can_be_restored(self):
        WishItem.objects.create(wishlist=Wishlist.objects.get(owner=self.user), title="Autor por identificar", author="")
        rows, _ = native_csv.parse_csv(upload(native_csv.export_csv(self.user)))
        native_csv.import_rows(self.other, rows)
        self.assertTrue(WishItem.objects.filter(wishlist__owner=self.other, title="Autor por identificar", author="").exists())

    def test_repeated_readings_and_historical_reviews_are_not_collapsed(self):
        work = Work.objects.create(title="Obra", author="Autora", identity="test:work")
        edition = Edition.objects.create(title="Obra", author="Autora", work=work, isbn="9788408163435")
        old = Book.objects.create(owner=self.user, title="Obra", author="Autora", catalog_edition=edition)
        new = Book.objects.create(owner=self.user, title="Obra", author="Autora", catalog_edition=edition)
        Review.objects.create(book=old, text="Antes", is_current=False)
        Review.objects.create(book=new, text="Ahora", is_current=True)
        rows, _ = native_csv.parse_csv(upload(native_csv.export_csv(self.user)))
        native_csv.import_rows(self.other, rows)
        self.assertEqual(Book.objects.filter(owner=self.other, title="Obra").count(), 2)
        self.assertEqual(Review.objects.filter(owner=self.other, work=work).count(), 2)
        self.assertEqual(Review.objects.get(owner=self.other, work=work, is_current=True).text, "Ahora")

    def test_token_is_bound_to_owner_and_csrf_is_required(self):
        token = self.client.post(self.url, {"source": "entrelineas", "file": upload(native_csv.export_csv(self.user))}).context["token"]
        self.client.force_login(self.other)
        self.assertContains(self.client.post(self.url, {"action": "confirm", "token": token}), "caducado")
        client = Client(enforce_csrf_checks=True); client.force_login(self.user)
        self.assertEqual(client.post(self.url, {"action": "confirm", "token": token}).status_code, 403)

    def test_csv_format_is_language_independent_and_controls_exist_in_every_language(self):
        for language in ("es", "en", "de", "fr", "it"):
            with self.subTest(language=language), translation.override(language):
                rows, _ = native_csv.parse_csv(upload(native_csv.export_csv(self.user)))
                self.assertEqual(rows[0]["review_rating"], "4.25")
                target = reverse("library_transfer")
                for name in ("library", "profile"):
                    response = self.client.get(reverse(name))
                    self.assertContains(response, f'href="{target}"')
                    self.assertNotContains(response, f'href="{reverse("library_export")}"')
                response = self.client.get(target)
                self.assertContains(response, 'value="goodreads"')
                self.assertContains(response, 'value="entrelineas"')

    def test_unified_entry_has_two_paths_and_private_export_summary(self):
        response = self.client.get(reverse("library_transfer"))
        self.assertEqual(response.context["transfer_stage"], "direction")
        self.assertContains(response, 'data-transfer-action="import"')
        self.assertContains(response, 'data-transfer-action="export"')
        self.assertEqual(response.context["export_summary"], {"books": 1, "reviews": 1, "wishes": 1})
        export = self.client.get(reverse("library_transfer"), {"direction": "export"})
        self.assertEqual(export.context["transfer_stage"], "export")
        self.assertContains(export, 'data-export-download')
        self.assertEqual(self.client.get(reverse("library_import")).context["transfer_stage"], "source")
        self.client.force_login(self.other)
        empty = self.client.get(reverse("library_transfer"))
        self.assertEqual(empty.context["export_summary"], {"books": 0, "reviews": 0, "wishes": 0})
        self.assertEqual(Client().get(reverse("library_transfer")).status_code, 302)

    def test_guided_upload_uses_radio_options_and_preserves_source_after_errors(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'data-wizard-step="source"')
        self.assertContains(response, 'data-wizard-step="file"')
        self.assertContains(response, 'data-wizard-step="loading"')
        self.assertContains(response, 'type="radio"', count=2)
        self.assertNotContains(response, '<select')
        self.assertContains(response, 'data-upload-submit')
        response = self.client.post(self.url, {'source': 'entrelineas', 'file': upload(b'not a CSV')})
        self.assertContains(response, 'No reconocemos este CSV')
        self.assertTrue(response.context['form']['source'].value() == 'entrelineas')
        self.assertEqual(Book.objects.filter(owner=self.other).count(), 0)
