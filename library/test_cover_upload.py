from django.test import Client
from django.urls import reverse
from .tests import AppTestCase
from .test_manual_editions import photo
from .test_catalog import edition_data
from .catalog_store import store_edition
from .catalog_views import _sign
from .models import Book, Edition, ReadingNote, Review
from django.test import RequestFactory
from unittest.mock import patch


class ExistingCoverTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.user = self.make_user()
        self.client.force_login(self.user)
        data = edition_data("bne", "991061150881508606")
        data.update(title="Toda mi violencia es tuya", author="José Serralvo", work_key=data["source_id"], cover_url="")
        self.edition = store_edition(data)
        self.book = Book.objects.create(owner=self.user, catalog_edition=self.edition, title=self.edition.title,
                                       author=self.edition.author, current_page=25, total_pages=592)
        self.url = reverse("book_cover", args=[self.book.pk])

    def token(self, data):
        request = RequestFactory().get("/")
        request.user = self.user
        return _sign(request, data)

    def test_upload_existing_edition_keeps_bibliography_reviews_and_progress(self):
        review = Review.objects.create(book=self.book, text="Mi reseña")
        note = ReadingNote.objects.create(book=self.book, text="Mi nota", page=20)
        before = (self.edition.title, self.edition.author, self.edition.isbn, self.edition.work_id)
        self.assertContains(self.client.get(self.book.get_absolute_url()), "Añadir portada")
        self.assertContains(self.client.get(self.url), "Guardar portada")
        self.assertRedirects(self.client.post(self.url, {"cover": photo()}), self.book.get_absolute_url())
        self.edition.refresh_from_db(); self.book.refresh_from_db(); review.refresh_from_db()
        self.assertEqual((self.edition.title, self.edition.author, self.edition.isbn, self.edition.work_id), before)
        self.assertEqual(self.edition.origin, "external")
        self.assertEqual(self.edition.cover_added_by, self.user)
        self.assertIsNotNone(self.edition.cover_added_at)
        self.assertEqual(self.edition.field_sources["cover_image"], "user")
        self.assertEqual(self.book.current_page, 25)
        self.assertEqual(review.text, "Mi reseña")
        self.assertTrue(ReadingNote.objects.filter(pk=note.pk).exists())
        self.assertEqual(self.edition.sources.count(), 1)
        self.assertNotContains(self.client.get(self.book.get_absolute_url()), "data-cover-upload")

    def test_adding_cover_is_shared_for_same_edition_and_preserves_external_url(self):
        self.edition.cover_url = "https://covers.openlibrary.org/b/id/1234-M.jpg?default=false"
        self.edition.save()
        other = self.make_user("other@example.com")
        other_book = Book.objects.create(owner=other, catalog_edition=self.edition, title=self.edition.title, author=self.edition.author)
        self.client.post(self.url, {"cover": photo()})
        self.edition.refresh_from_db(); other_book.refresh_from_db()
        self.assertTrue(self.edition.cover_url.startswith("https://covers.openlibrary.org/"))
        self.assertEqual(other_book.cover_url, self.edition.display_cover_url)
        self.assertTrue(other_book.cover_url.startswith("/es/portadas/"))

    def test_empty_invalid_and_duplicate_uploads_do_not_replace_existing_photo(self):
        self.assertContains(self.client.post(self.url, {}), "Este campo es obligatorio")
        self.edition.refresh_from_db()
        self.assertFalse(self.edition.cover_image)
        self.client.post(self.url, {"cover": photo()})
        self.edition.refresh_from_db()
        filename = self.edition.cover_image.name
        self.assertRedirects(self.client.post(self.url, {"cover": photo("PNG")}), self.book.get_absolute_url())
        self.edition.refresh_from_db()
        self.assertEqual(self.edition.cover_image.name, filename)
        self.assertEqual(Edition.objects.count(), 1)

    def test_only_reading_owner_can_upload_and_csrf_is_required(self):
        self.assertEqual(Client().get(self.url).status_code, 302)
        self.client.force_login(self.make_user("other@example.com"))
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.client.post(self.url, {"cover": photo()}).status_code, 404)
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.user)
        self.assertEqual(csrf.post(self.url, {"cover": photo()}).status_code, 403)
        self.edition.refresh_from_db()
        self.assertFalse(self.edition.cover_image)

    def test_preview_offers_save_then_upload_for_coverless_external_record(self):
        data = edition_data("bne", "991011069219708606", isbn="9788433934345")
        data.update(title="La conjura de los necios", author="John Kennedy Toole", work_key=data["source_id"], cover_url="")
        with patch("library.catalog.details", return_value=data):
            response = self.client.get(reverse("catalog_preview"), {"selection": self.token(data)})
        self.assertContains(response, 'name="destination" value="cover"')
        response = self.client.post(reverse("catalog_save"), {"selection": response.context["selection"], "destination": "cover"})
        book = Book.objects.get(catalog_edition__isbn="9788433934345")
        self.assertRedirects(response, reverse("book_cover", args=[book.pk]))
        self.assertFalse(book.catalog_edition.cover_image)
