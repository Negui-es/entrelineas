from unittest.mock import patch

from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse

from . import catalog
from .catalog_store import store_edition
from .goodreads import parse_export, import_rows
from .goodreads_catalog import prepare_rows, choose, match_remote
from .models import Book, Edition, GoodreadsEntry, Review, WishItem
from .test_catalog import edition_data
from .test_goodreads import export
from .tests import AppTestCase


@override_settings(SECURE_SSL_REDIRECT=False)
class GoodreadsCatalogTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.user = self.make_user()
        self.client.force_login(self.user)
        self.url = reverse("goodreads_import")

    def rows(self, **changes):
        return parse_export(export(changes))[0]

    def test_isbn_reuses_exact_edition_and_borrows_work_cover(self):
        exact = edition_data()
        exact["cover_url"] = ""
        exact["synopsis"] = ""
        edition = store_edition(exact)
        other = store_edition(edition_data(external_id="OL99M", isbn="9780140328721", pages=96))
        rows = prepare_rows(self.rows())
        self.assertEqual(rows[0]["match_isbn"], edition.isbn)
        self.assertEqual(rows[0]["match_cover"], other.cover_url)
        self.assertTrue(rows[0]["match_cover_from_work"])
        with patch.object(catalog, "search") as search:
            match_remote(rows[0])
            search.assert_not_called()
        import_rows(self.user, rows)
        book = Book.objects.get()
        self.assertEqual(book.catalog_edition_id, edition.pk)
        self.assertEqual(book.metadata.total_pages, 592)
        self.assertEqual(book.cover_url, other.cover_url)
        edition.refresh_from_db()
        self.assertEqual(edition.cover_url, "")
        self.assertEqual(edition.isbn, "9788408163435")

    def test_unrelated_work_cannot_supply_a_cover(self):
        data = edition_data()
        data["cover_url"] = ""
        edition = store_edition(data)
        other = edition_data(external_id="OL99M", isbn="9780140328721")
        other.update(title="Otro libro", author="Otra Autora", work_key="/works/OL99W")
        store_edition(other)
        self.assertEqual(edition.display_cover_url, "")
        self.assertEqual(prepare_rows(self.rows())[0]["match_cover"], "")
        row = self.rows()[0]
        self.assertIsNone(choose(row, [{**data, "author": "Otra Autora"}]))
        self.assertIsNone(choose(row, [{**data, "title": "La sombra del viento, novela gráfica"}]))

    def test_external_matching_stays_in_preview_until_confirmation(self):
        response = self.client.post(self.url, {"file": export()})
        token = response.context["token"]
        data = edition_data()
        with patch.object(catalog, "search", return_value={"items": [data]}) as search, patch.object(catalog, "details", return_value=data):
            response = self.client.post(self.url, {"action": "match", "token": token, "index": 0})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["match_cover"], data["cover_url"])
        search.assert_called_once_with("9788408163435", "isbn")
        self.assertEqual(Edition.objects.count(), 0)
        self.assertEqual(Book.objects.count(), 0)
        self.client.post(self.url, {"action": "confirm", "token": token})
        book = Book.objects.get()
        self.assertEqual(book.cover_url, data["cover_url"])
        self.assertEqual(book.metadata.publisher, "Planeta")
        self.assertEqual(book.metadata.synopsis, data["synopsis"])
        self.assertEqual(Review.objects.get().text, 'Una historia, preciosa.\nCon "alma".')

    def test_remote_fallback_keeps_exact_isbn_and_pages(self):
        exact = edition_data()
        exact["cover_url"] = ""
        other = edition_data(external_id="OL99M", isbn="9780140328721", pages=96)
        row = prepare_rows(self.rows())[0]
        def search(query, mode):
            return {"items": [exact] if mode == "isbn" else [other]}
        with patch.object(catalog, "search", side_effect=search), patch.object(catalog, "details", side_effect=lambda selection: exact if selection["source_id"] == exact["source_id"] else other):
            match_remote(row)
        self.assertEqual(row["match_isbn"], exact["isbn"])
        self.assertTrue(row["match_cover_from_work"])
        import_rows(self.user, [row])
        book = Book.objects.get()
        self.assertEqual(book.metadata.isbn, exact["isbn"])
        self.assertEqual(book.metadata.total_pages, 592)
        self.assertEqual(book.cover_url, other["cover_url"])
        self.assertEqual(Edition.objects.count(), 2)

    def test_title_author_and_wishes_can_link_without_csv_isbn(self):
        edition = store_edition(edition_data())
        rows = prepare_rows(self.rows(ISBN13="", **{"Exclusive Shelf": "to-read", "My Review": "", "My Rating": "0", "Date Read": ""}))
        self.assertIn("título y autor", rows[0]["match_label"])
        counts = import_rows(self.user, rows)
        self.assertEqual(counts["wishes"], 1)
        self.assertEqual(WishItem.objects.get().catalog_edition_id, edition.pk)

    def test_repeat_import_links_existing_book_without_replacing_review(self):
        rows = self.rows()
        import_rows(self.user, rows)
        book = Book.objects.get()
        review = Review.objects.get()
        edition = store_edition(edition_data())
        rows = prepare_rows(self.rows())
        counts = import_rows(self.user, rows)
        self.assertEqual(counts["linked"], 1)
        self.assertEqual(counts["books"], 0)
        self.assertEqual(Book.objects.count(), 1)
        self.assertEqual(Review.objects.count(), 1)
        book.refresh_from_db()
        review.refresh_from_db()
        self.assertEqual(book.catalog_edition_id, edition.pk)
        self.assertEqual(review.work_id, edition.work_id)
        self.assertEqual(review.rating, 4)
        self.assertEqual(review.book_id, book.pk)
        self.assertEqual(import_rows(self.user, rows)["linked"], 0)

    def test_matched_catalog_identity_avoids_duplicate_with_csv_typo(self):
        edition = store_edition(edition_data())
        book = Book.objects.create(owner=self.user, title=edition.title, author=edition.author, catalog_edition=edition)
        rows = prepare_rows(self.rows(Title="La sombra del vientoo", ISBN13=""))
        self.assertTrue(rows[0]["catalog_data"])
        counts = import_rows(self.user, rows)
        self.assertEqual(counts["books"], 0)
        self.assertEqual(Book.objects.get().pk, book.pk)

    def test_missing_catalog_fields_are_filled_without_overwriting(self):
        original = edition_data()
        original.update(cover_url="", synopsis="")
        edition = store_edition(original)
        remote = edition_data()
        remote.update(total_pages=300, publisher="Otra editorial")
        row = prepare_rows(self.rows())[0]
        with patch.object(catalog, "search", return_value={"items": [remote]}), patch.object(catalog, "details", return_value=remote):
            match_remote(row)
        import_rows(self.user, [row])
        edition.refresh_from_db()
        self.assertEqual(edition.total_pages, 592)
        self.assertEqual(edition.publisher, "Planeta")
        self.assertEqual(edition.cover_url, remote["cover_url"])
        self.assertEqual(edition.synopsis, remote["synopsis"])

    def test_failure_and_account_isolation_do_not_lose_csv(self):
        token = self.client.post(self.url, {"file": export()}).context["token"]
        other = self.make_user("other@example.com")
        self.client.force_login(other)
        self.assertEqual(self.client.post(self.url, {"action": "match", "token": token, "index": 0}).status_code, 404)
        self.client.force_login(self.user)
        with patch.object(catalog, "search", side_effect=catalog.CatalogError("offline")):
            response = self.client.post(self.url, {"action": "match", "token": token, "index": 0})
        self.assertEqual(response.status_code, 200)
        self.client.post(self.url, {"action": "confirm", "token": token})
        self.assertEqual(Book.objects.count(), 1)
        self.assertEqual(Review.objects.get().rating, 4)
        self.assertEqual(self.client.post(self.url, {"action": "match", "token": token, "index": 0}).status_code, 404)

    def test_confirm_does_not_race_with_matching(self):
        token = self.client.post(self.url, {"file": export()}).context["token"]
        cache.set(f"goodreads:v3:{self.user.pk}:{token}:lock", True)
        self.assertEqual(self.client.post(self.url, {"action": "match", "token": token, "index": 0}).status_code, 409)
        self.client.post(self.url, {"action": "confirm", "token": token})
        self.assertEqual(Book.objects.count(), 0)
