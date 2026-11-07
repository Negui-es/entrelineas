import csv
import io
from datetime import date

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import translation

from .goodreads import parse_export, import_rows, MAX_BYTES
from .models import Book, GoodreadsEntry, Review, WishItem, Wishlist
from .tests import AppTestCase
from .test_catalog import edition_data
from .catalog_store import store_edition


def export(*changes):
    base = {"Book Id": "123", "Title": "La sombra del viento", "Author": "Carlos Ruiz Zafón",
            "ISBN13": '="9788408163435"', "My Rating": "4", "My Review": 'Una historia, preciosa.<br>Con "alma".',
            "Exclusive Shelf": "read", "Date Read": "2025/03/14", "Number of Pages": "400"}
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=list(base))
    writer.writeheader()
    for change in changes or ({},):
        writer.writerow({**base, **change})
    return SimpleUploadedFile("goodreads_library_export.csv", output.getvalue().encode("utf-8-sig"), content_type="text/csv")


@override_settings(SECURE_SSL_REDIRECT=False)
class GoodreadsTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.user = self.make_user()
        self.client.force_login(self.user)
        self.url = reverse("goodreads_import")

    def test_preview_confirm_and_repeat_are_additive(self):
        response = self.client.post(self.url, {"file": export()})
        self.assertContains(response, "Confirmar importación")
        self.assertContains(response, 'data-import-progress max="1" value="0"')
        self.assertContains(response, 'data-goodreads-id="123"')
        self.assertEqual(response.context["match_titles"], ["La sombra del viento"])
        self.assertEqual(Book.objects.count(), 0)
        token = response.context["token"]
        result = self.client.post(self.url, {"action": "confirm", "token": token})
        self.assertEqual(result.context["result"]["books"], 1)
        book = Book.objects.get()
        review = Review.objects.get()
        self.assertEqual(book.finished_at, date(2025, 3, 14))
        self.assertEqual(book.current_page, 400)
        self.assertEqual(book.isbn, "9788408163435")
        self.assertEqual(review.text, 'Una historia, preciosa.\nCon "alma".')
        self.assertEqual(review.rating, 4)
        self.assertEqual(review.visibility, "private")
        self.assertFalse(review.is_draft)
        self.assertContains(self.client.get(book.get_absolute_url()), "La sombra del viento")
        self.assertContains(self.client.get(reverse("reviews")), "Una historia")
        expired = self.client.post(self.url, {"action": "confirm", "token": token})
        self.assertContains(expired, "caducado")
        rows, _ = parse_export(export({"Title": "Otro título"}))
        self.assertEqual(import_rows(self.user, rows)["skipped"], 1)
        self.assertEqual(Book.objects.count(), 1)

    @override_settings(DEBUG=False)
    def test_library_and_profile_link_to_import_in_every_language(self):
        for language in ("es", "en", "de", "fr", "it"):
            with self.subTest(language=language), translation.override(language):
                target = reverse("library_transfer")
                for page in ("library", "profile"):
                    self.assertContains(self.client.get(reverse(page)), f'href="{target}"')
                self.assertContains(self.client.get(target), 'name="file"')

    def test_existing_catalog_reading_and_review_are_preserved(self):
        edition = store_edition(edition_data())
        book = Book.objects.create(owner=self.user, catalog_edition=edition, title=edition.title, author=edition.author, status="reading")
        review = Review.objects.create(owner=self.user, book=book, rating=2, text="Mi reseña")
        rows, _ = parse_export(export())
        counts = import_rows(self.user, rows)
        self.assertEqual(counts, {"books": 0, "wishes": 0, "reviews": 0, "skipped": 0, "kept_reviews": 1, "linked": 0})
        book.refresh_from_db()
        review.refresh_from_db()
        self.assertEqual(book.status, "reading")
        self.assertEqual(review.text, "Mi reseña")
        self.assertEqual(review.rating, 2)

    def test_new_reading_reuses_catalog_without_modifying_metadata(self):
        edition = store_edition(edition_data())
        rows, _ = parse_export(export())
        import_rows(self.user, rows)
        book = Book.objects.get()
        self.assertEqual(book.catalog_edition, edition)
        self.assertEqual(Review.objects.get().work, edition.work)
        edition.refresh_from_db()
        self.assertEqual(edition.total_pages, edition_data()["total_pages"])

    def test_validation_and_duplicate_rows(self):
        for raw in (b"Title,Author\nx,y", b"\xff\xfe", b"x" * (MAX_BYTES + 1)):
            with self.assertRaises(ValidationError):
                parse_export(SimpleUploadedFile("bad.csv", raw))
        rows, issues = parse_export(export({}, {}, {"Book Id": "456", "Title": "Otro", "My Rating": "9"},
                                         {"Book Id": "789", "Date Read": "ayer", "My Rating": "0", "Exclusive Shelf": "custom"}))
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(issues), 4)
        self.assertIsNone(rows[1]["finished_at"])
        self.assertIsNone(rows[1]["rating"])
        self.assertEqual(rows[1]["status"], "pending")
        self.assertEqual(self.client.post(self.url, {"file": SimpleUploadedFile("bad.csv", b"bad")}).status_code, 200)

    def test_account_and_preview_isolation_expiry_and_csrf(self):
        self.assertEqual(Client().get(self.url).status_code, 302)
        token = self.client.post(self.url, {"file": export()}).context["token"]
        other = self.make_user("other@example.com")
        self.client.force_login(other)
        self.assertContains(self.client.post(self.url, {"action": "confirm", "token": token}), "caducado")
        self.assertEqual(Book.objects.count(), 0)
        self.client.force_login(self.user)
        cache.clear()
        self.assertContains(self.client.post(self.url, {"action": "confirm", "token": token}), "caducado")
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        self.assertEqual(csrf_client.post(self.url, {"action": "confirm", "token": token}).status_code, 403)
        self.client.force_login(self.make_user("unverified@example.com", verified=False))
        self.assertTemplateUsed(self.client.get(self.url), "account/verified_email_required.html")

    def test_html_is_escaped_and_multiline_text_survives(self):
        response = self.client.post(self.url, {"file": export({"Title": '<img src=x onerror=alert(1)>', "My Review": 'Línea uno\nLínea dos &lt;img src=x onerror=alert(1)&gt;'})})
        self.assertContains(response, "&lt;img")
        self.assertNotContains(response, "<img src=x")
        self.assertIn("Línea uno\nLínea dos", cache.get(f'goodreads:v3:{self.user.pk}:{response.context["token"]}')[0]["text"])

    def test_decimal_ratings_and_invalid_fractional_values(self):
        for rating, expected in [("3.0", 3), ("5.00", 5), ("0.0", None), ("4", 4)]:
            with self.subTest(rating=rating):
                rows, issues = parse_export(export({"My Rating": rating}))
                self.assertEqual(rows[0]["rating"], expected)
                self.assertEqual(issues, [])
        for invalid in ("3.5", "NaN", "Infinity", "-1", "6.0"):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                parse_export(export({"My Rating": invalid}))

    def test_split_read_reviewed_reading_and_wanted_books(self):
        response = self.client.post(self.url, {"file": export(*[{**row, "ISBN13": ""} for row in (
            {"Book Id": "1", "Title": "Leído", "My Rating": "3.0"},
            {"Book Id": "2", "Title": "Leyendo", "Exclusive Shelf": "currently-reading", "My Rating": "0", "My Review": "", "Date Read": ""},
            {"Book Id": "3", "Title": "Deseado", "ISBN13": "", "Exclusive Shelf": "to-read", "My Rating": "0", "My Review": "", "Date Read": ""},
            {"Book Id": "4", "Title": "Con reseña", "Exclusive Shelf": "to-read", "My Rating": "0", "Date Read": ""},
            {"Book Id": "5", "Title": "Con estrellas", "Exclusive Shelf": "to-read", "My Rating": "4.0", "My Review": "", "Date Read": ""},
        )])})
        self.assertEqual(response.context["library_count"], 4)
        self.assertEqual(response.context["wish_count"], 1)
        self.assertEqual(Book.objects.count(), 0)
        self.assertEqual(WishItem.objects.count(), 0)
        key = f'goodreads:v3:{self.user.pk}:{response.context["token"]}'
        rows = cache.get(key)
        result = self.client.post(self.url, {"action": "confirm", "token": response.context["token"]})
        self.assertEqual(result.context["result"]["wishes"], 1)
        self.assertEqual(Book.objects.count(), 4)
        self.assertEqual(Review.objects.count(), 3)
        self.assertEqual(WishItem.objects.get().title, "Deseado")
        self.assertFalse(Book.objects.filter(title="Deseado").exists())
        self.assertEqual(import_rows(self.user, rows)["skipped"], 5)
        self.assertEqual(WishItem.objects.count(), 1)

    def test_existing_wish_is_reused_and_scoped_to_owner(self):
        listing = Wishlist.objects.create(owner=self.user)
        wish = WishItem.objects.create(wishlist=listing, title="Deseado", author="Autora", priority="high")
        rows, _ = parse_export(export({"Title": "Deseado", "Author": "Autora", "ISBN13": "", "My Review": "", "My Rating": "0.0", "Exclusive Shelf": "to-read", "Date Read": ""}))
        self.assertEqual(import_rows(self.user, rows)["wishes"], 0)
        self.assertEqual(GoodreadsEntry.objects.get().wish, wish)
        self.assertEqual(WishItem.objects.get().priority, "high")
        other = self.make_user("other@example.com")
        self.assertEqual(import_rows(other, rows)["wishes"], 1)
        self.assertEqual(WishItem.objects.count(), 2)

    def test_spoiler_flag_is_preserved(self):
        upload = export()
        raw = upload.read().decode("utf-8-sig")
        source = list(csv.DictReader(io.StringIO(raw)))[0]
        source["Spoiler"] = "true"
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=list(source))
        writer.writeheader()
        writer.writerow(source)
        rows, _ = parse_export(SimpleUploadedFile("spoilers.csv", output.getvalue().encode()))
        import_rows(self.user, rows)
        self.assertTrue(Review.objects.get().contains_spoilers)

    def test_existing_private_book_without_isbn_gets_only_missing_review(self):
        book = Book.objects.create(owner=self.user, title="La sombra del viento", author="Carlos Ruiz Zafón")
        rows, _ = parse_export(export({"ISBN13": ""}))
        counts = import_rows(self.user, rows)
        self.assertEqual(counts["books"], 0)
        self.assertEqual(counts["reviews"], 1)
        self.assertEqual(Review.objects.get().book, book)
        self.assertEqual(GoodreadsEntry.objects.get().owner, self.user)
