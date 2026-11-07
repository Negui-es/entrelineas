from unittest.mock import patch
from django.core import signing
from django.test import RequestFactory
from django.urls import reverse
from .tests import AppTestCase
from . import catalog
from .catalog_views import _sign
from .catalog_store import store_edition
from .models import Book, CatalogSource, Edition, ReadingNote, Review, Work


def edition_data(provider="openlibrary", external_id="OL37070014M", isbn="9788408163435", pages=592):
    data = {"provider": provider, "source_id": external_id, "work_key": "/works/OL278437W", "kind": "edition",
            "title": "La sombra del viento", "author": "Carlos Ruiz Zafón", "isbn": isbn,
            "publisher": "Planeta", "publication_date": "2017", "language": "es", "total_pages": pages,
            "cover_url": "https://covers.openlibrary.org/b/id/10107644-M.jpg", "synopsis": "Una historia de libros.",
            "field_sources": {"title": provider}, "conflicts": []}
    data["sources"] = [{"provider": provider, "external_id": external_id, "url": "https://openlibrary.org/books/" + external_id,
                        "metadata": {"title": data["title"], "isbn": isbn, "total_pages": pages}}]
    return data


class CatalogTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.user = self.make_user()
        self.client.force_login(self.user)

    def token(self, data, target=None, user=None):
        request = RequestFactory().get("/")
        request.user = user or self.user
        return _sign(request, data, target)

    def test_isbn_validation_and_equivalent_identifiers(self):
        self.assertEqual(catalog.canonical_isbn("84-08-16343-4"), "9788408163435")
        self.assertEqual(catalog.canonical_isbn("978 84 08 16343 5"), "9788408163435")
        self.assertEqual(catalog.canonical_isbn("9788408163436"), "")
        self.assertEqual(catalog.canonical_isbn("1234567890123"), "")
        with patch.object(catalog, "_worker") as worker:
            with self.assertRaises(catalog.CatalogError):
                catalog.search("9788408163436", "isbn")
            worker.assert_not_called()

    def test_federated_search_groups_same_isbn_and_survives_provider_failure(self):
        first = {"provider": "openlibrary", "source_id": "OL37070014M", "kind": "edition", "title": "La sombra", "author": "Zafón", "isbn": "8408163434"}
        second = {**first, "provider": "inventaire", "source_id": "inv:" + "a" * 32, "isbn": "9788408163435"}
        with patch.object(catalog, "_worker", side_effect=lambda p, *a: {"items": [first if p == "openlibrary" else second], "has_next": False}):
            result = catalog.search("La sombra", "title")
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(len(result["items"][0]["alternatives"]), 1)
        with patch.object(catalog, "_worker", side_effect=lambda p, *a: {"items": [first], "has_next": False} if p == "openlibrary" else (_ for _ in ()).throw(catalog.CatalogError("offline"))):
            result = catalog.search("La sombra")
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(len(result["failed_providers"]), 3)
        self.assertEqual(result["warnings"], [])

    def test_same_title_without_isbn_does_not_merge_editions(self):
        raw = {"provider": "openlibrary", "source_id": "OL1M", "kind": "edition", "title": "Libro", "author": "Autora", "isbn": ""}
        with patch.object(catalog, "_worker", side_effect=lambda p, *a: {"items": [{**raw, "provider": p}], "has_next": False}):
            self.assertEqual(len(catalog.search("Libro")["items"]), 4)

    def test_store_has_shared_ids_and_distinct_editions_under_one_work(self):
        data = edition_data()
        first = store_edition(data)
        self.assertEqual(store_edition(data).pk, first.pk)
        second = store_edition(edition_data(external_id="OL99M", isbn="9780140328721", pages=96))
        self.assertEqual(first.work_id, second.work_id)
        self.assertNotEqual(first.pk, second.pk)
        other = edition_data("inventaire", "inv:" + "a" * 32)
        self.assertEqual(store_edition(other).pk, first.pk)
        self.assertEqual(first.sources.count(), 2)

    def test_another_source_cannot_silently_overwrite_selected_pages(self):
        first = store_edition(edition_data())
        other = edition_data("inventaire", "inv:" + "a" * 32, pages=300)
        store_edition(other)
        first.refresh_from_db()
        self.assertEqual(first.total_pages, 592)
        self.assertEqual(CatalogSource.objects.get(provider="inventaire").metadata["total_pages"], 300)

    def test_import_reuses_catalogue_but_keeps_users_readings_separate(self):
        token = self.token(edition_data())
        self.client.post(reverse("catalog_save"), {"selection": token, "destination": "library"})
        self.client.post(reverse("catalog_save"), {"selection": token, "destination": "library"})
        first = Book.objects.get(owner=self.user)
        Review.objects.create(book=first, text="RESEÑA PRIVADA DEL PRIMERO")
        ReadingNote.objects.create(book=first, text="NOTA PRIVADA DEL PRIMERO")
        other = self.make_user("otra@example.com")
        self.client.force_login(other)
        self.client.post(reverse("catalog_save"), {"selection": self.token(edition_data(), user=other), "destination": "library"})
        second = Book.objects.get(owner=other)
        self.assertEqual(first.catalog_edition_id, second.catalog_edition_id)
        self.assertEqual(Edition.objects.count(), 1)
        page = self.client.get(second.get_absolute_url())
        self.assertNotContains(page, "RESEÑA PRIVADA DEL PRIMERO")
        self.assertNotContains(page, "NOTA PRIVADA DEL PRIMERO")
        self.assertEqual(self.client.get(first.get_absolute_url()).status_code, 404)

    def test_existing_reading_links_without_losing_private_data(self):
        book = Book.objects.create(owner=self.user, title="Mi ficha", author="Autora", current_page=45, total_pages=200, status="reading")
        review = Review.objects.create(book=book, text="Mis recuerdos")
        note = ReadingNote.objects.create(book=book, text="Mi apunte", page=20)
        response = self.client.post(reverse("catalog_save"), {"selection": self.token(edition_data(), book.pk), "destination": "link"})
        self.assertRedirects(response, book.get_absolute_url())
        book.refresh_from_db()
        self.assertEqual(book.metadata.title, "La sombra del viento")
        self.assertEqual(book.current_page, 45)
        self.assertEqual(book.status, "reading")
        self.assertEqual(Review.objects.get(pk=review.pk).text, "Mis recuerdos")
        self.assertTrue(ReadingNote.objects.filter(pk=note.pk, book=book).exists())

    def test_cannot_link_another_users_book_or_tamper_with_selection(self):
        other = self.make_user("otra@example.com")
        book = Book.objects.create(owner=other, title="Privado", author="Autora")
        self.assertEqual(self.client.get(reverse("catalog_search"), {"link": book.pk}).status_code, 404)
        self.assertEqual(self.client.post(reverse("catalog_save"), {"selection": self.token(edition_data(), book.pk), "destination": "link"}).status_code, 404)
        token = self.token(edition_data())
        self.assertEqual(self.client.post(reverse("catalog_save"), {"selection": token + "bad", "destination": "library"}).status_code, 404)
        self.assertEqual(Edition.objects.count(), 0)
        self.client.force_login(other)
        self.assertEqual(self.client.post(reverse("catalog_save"), {"selection": token, "destination": "library"}).status_code, 404)

    def test_link_refuses_to_reset_progress_when_edition_is_shorter(self):
        book = Book.objects.create(owner=self.user, title="Libro", author="Autora", current_page=150, total_pages=200)
        self.client.post(reverse("catalog_save"), {"selection": self.token(edition_data(pages=100), book.pk), "destination": "link"})
        book.refresh_from_db()
        self.assertEqual(book.current_page, 150)
        self.assertIsNone(book.catalog_edition_id)
        self.assertEqual(Edition.objects.count(), 0)

    def test_shared_metadata_is_not_editable_through_personal_forms(self):
        edition = store_edition(edition_data())
        book = Book.objects.create(owner=self.user, catalog_edition=edition, title=edition.title, author=edition.author, isbn=edition.isbn, total_pages=edition.total_pages)
        self.client.post(reverse("book_edit", args=[book.pk]), {"title": "Ataque", "author": "Otro", "isbn": "1", "total_pages": 1, "color": "blue", "status": "reading", "current_page": 40})
        book.refresh_from_db(); edition.refresh_from_db()
        self.assertEqual(edition.title, "La sombra del viento")
        self.assertEqual(book.current_page, 40)
        self.assertEqual(book.metadata.total_pages, 592)

    def test_search_and_preview_dont_create_catalogue_records(self):
        data = edition_data()
        with patch.object(catalog, "search", return_value={"items": [data], "warnings": [], "total": 1, "has_next": False}):
            self.assertContains(self.client.get(reverse("catalog_search"), {"q": "La sombra"}), "Ver edición")
        with patch.object(catalog, "details", return_value=data):
            self.assertContains(self.client.get(reverse("catalog_preview"), {"selection": self.token(data)}), "A mi biblioteca")
        self.assertEqual(Edition.objects.count(), 0)
        self.assertEqual(self.client.get(reverse("catalog_save")).status_code, 405)

    def test_covers_only_use_approved_origins(self):
        self.assertEqual(catalog.safe_cover("https://evil.example/track"), "")
        self.assertEqual(catalog.safe_cover("https://inventaire.io@evil.example/a"), "")
        self.assertEqual(catalog.safe_cover("http://covers.openlibrary.org/a"), "")
        self.assertTrue(catalog.safe_cover("/img/entities/" + "a" * 40).startswith("https://inventaire.io/"))

    def test_inventaire_author_work_objects_are_resolved(self):
        selection = {"source_id": "wd:Q296752", "kind": "author"}
        with patch.object(catalog, "_request", return_value={"works": [{"uri": "wd:Q52910", "score": 134}]}), patch.object(catalog, "inv_entities", return_value={"wd:Q52910": {"uri": "wd:Q52910", "type": "work", "labels": {"es": "La sombra del viento"}}}) as entities:
            results = catalog.inventaire_options(selection)
        entities.assert_called_once_with(["wd:Q52910"])
        self.assertEqual(results[0]["title"], "La sombra del viento")

    def test_openlibrary_edition_details_use_edition_cover_and_pages(self):
        selection = {"source_id": "OL37070014M", "author": "Carlos Ruiz Zafón", "title": "La sombra", "isbn": "9788408163435"}
        with patch.object(catalog, "_request", return_value={"title": "La sombra del viento", "isbn_13": ["9788408163435"], "publishers": ["Planeta"], "number_of_pages": 592, "covers": [12345], "description": "<script>bad</script>Descripción", "works": [{"key": "/works/OL278437W"}]}):
            result = catalog.openlibrary_details(selection)
        self.assertEqual(result["total_pages"], 592)
        self.assertIn("/12345-M.jpg", result["cover_url"])
        self.assertNotIn("<script>", result["synopsis"])
