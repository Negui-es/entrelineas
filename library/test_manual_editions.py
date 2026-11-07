from io import BytesIO
from unittest.mock import patch
from PIL import Image
from django.core import signing
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import Client
from django.urls import reverse
from .tests import AppTestCase
from .models import Book, Edition, Review, Work, ReadingNote
from .manual_forms import CoverForm
from .manual_views import SALT
from .catalog_store import store_edition
from .test_catalog import edition_data
from .work_identity import merge_works, work_candidates


def photo(format="JPEG", size=(200, 300)):
    output = BytesIO()
    Image.new("RGB", size, "purple").save(output, format=format)
    return SimpleUploadedFile("photo." + format.lower(), output.getvalue(), content_type="image/" + format.lower())


class ManualEditionTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.user = self.make_user()
        self.client.force_login(self.user)
        self.url = reverse("book_create")

    def details(self, **changes):
        data = {"action": "details", "isbn": "9788408163435", "title": "La sombra del viento", "author": "Carlos Ruiz Zafón", "language": "es"}
        data.update(changes)
        return self.client.post(self.url, data)

    def finish(self, response, **changes):
        data = {"action": "create", "selection": response.context["selection"], "cover": photo()}
        data.update(changes)
        return self.client.post(self.url, data)

    def test_requires_verified_account_and_valid_isbn(self):
        self.assertEqual(Client().get(self.url).status_code, 302)
        self.client.force_login(self.make_user("unverified@example.com", verified=False))
        self.assertTemplateUsed(self.client.post(self.url, {"action": "lookup", "isbn": "9788408163435"}), "account/verified_email_required.html")
        self.assertEqual(Edition.objects.count(), 0)
        self.client.force_login(self.user)
        response = self.client.post(self.url, {"action": "lookup", "isbn": "9788408163436"})
        self.assertContains(response, "Introduce un ISBN válido")
        self.assertEqual(Edition.objects.count(), 0)
        self.assertRedirects(self.client.post(self.url, {"action": "lookup", "isbn": "84-08-16343-4"}), self.url + "?isbn=9788408163435")

    def test_manual_creation_requires_all_fields_and_sanitises_cover(self):
        self.assertFalse(self.details(title="").context["metadata_form"].is_valid())
        response = self.details()
        self.assertEqual(Edition.objects.count(), 0)
        invalid = self.finish(response, cover="")
        self.assertIn("cover", invalid.context["cover_form"].errors)
        self.finish(response)
        edition = Edition.objects.get()
        book = Book.objects.get()
        self.assertEqual(book.catalog_edition, edition)
        self.assertEqual(edition.origin, "user")
        self.assertEqual(edition.work.origin, "user")
        self.assertEqual(edition.created_by, self.user)
        self.assertEqual(edition.work.created_by, self.user)
        self.assertFalse(edition.verified)
        self.assertEqual(edition.isbn, "9788408163435")
        with edition.cover_image.open("rb") as image:
            img = Image.open(image)
            self.assertEqual(img.format, "JPEG")
            self.assertFalse(img.getexif())
        cover = Client().get(edition.display_cover_url)
        self.assertEqual(cover.status_code, 200)
        self.assertEqual(cover["Content-Type"], "image/jpeg")
        b''.join(cover.streaming_content)

    def test_existing_isbn_is_reused_without_upload_or_metadata_changes(self):
        edition = store_edition(edition_data())
        page = self.client.get(self.url, {"isbn": "8408163434"})
        self.assertEqual(page.context["stage"], "existing")
        self.client.post(self.url, {"action": "reuse", "isbn": edition.isbn, "title": "Ataque"})
        self.client.post(self.url, {"action": "reuse", "isbn": edition.isbn})
        self.assertEqual(Book.objects.count(), 1)
        self.assertEqual(Edition.objects.count(), 1)
        edition.refresh_from_db()
        self.assertEqual(edition.title, "La sombra del viento")
        self.assertEqual(edition.origin, "external")

    def test_external_work_is_reused_with_normalised_author(self):
        original = store_edition(edition_data())
        page = self.details(isbn="9780140328721", author="Escrito por Zafón, Carlos Ruiz", language="en")
        self.assertEqual(page.context["matched_work"], original.work)
        self.finish(page)
        edition = Edition.objects.get(isbn="9780140328721")
        self.assertEqual(edition.work_id, original.work_id)
        self.assertEqual(edition.language, "en")
        self.assertEqual(edition.origin, "user")
        self.assertEqual(edition.work.origin, "external")
        self.assertEqual(Work.objects.count(), 1)

    def test_generic_title_requires_explicit_choice(self):
        work = Work.objects.create(identity="example:1", title="Cuentos", author="Ana María López")
        Edition.objects.create(work=work, title=work.title, author=work.author, isbn="9780140328721")
        page = self.details(title="Cuentos", author="Ana María López")
        self.assertIsNone(page.context["matched_work"])
        invalid = self.finish(page)
        self.assertIn("work", invalid.context["cover_form"].errors)
        self.finish(page, work=str(work.pk))
        self.assertEqual(Edition.objects.get(isbn="9788408163435").work_id, work.pk)

    def test_can_separate_ambiguous_works_and_cannot_choose_unrelated_work(self):
        generic = Work.objects.create(identity="example:1", title="Cuentos", author="Ana María López")
        unrelated = Work.objects.create(identity="example:2", title="Otra novela", author="Otro Autor")
        page = self.details(title="Cuentos", author="Ana María López")
        invalid = self.finish(page, work=str(unrelated.pk))
        self.assertIn("work", invalid.context["cover_form"].errors)
        self.assertEqual(Edition.objects.count(), 0)
        self.finish(page, work="new")
        self.assertNotEqual(Edition.objects.get().work_id, generic.pk)

    def test_tampered_expired_or_other_user_selection_cannot_create(self):
        page = self.details()
        token = page.context["selection"]
        self.finish(page, selection=token + "broken")
        with patch("django.core.signing.time.time", return_value=0):
            old = signing.dumps({"user": self.user.pk, "data": {"isbn": "9788408163435"}}, salt=SALT)
        self.finish(page, selection=old)
        self.client.force_login(self.make_user("other@example.com"))
        self.finish(page)
        self.assertEqual(Edition.objects.count(), 0)
        self.assertEqual(Book.objects.count(), 0)

    def test_race_or_replay_never_duplicates_isbn(self):
        page = self.details()
        original = store_edition(edition_data())
        response = self.finish(page)
        self.assertEqual(response.context["stage"], "existing")
        self.assertEqual(Book.objects.count(), 0)
        self.client.post(self.url, {"action": "reuse", "isbn": original.isbn})
        self.assertEqual(Edition.objects.count(), 1)
        self.assertEqual(Book.objects.count(), 1)
        self.assertFalse(original.cover_image)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Edition.objects.create(work=original.work, title="Otro", author="Otro", isbn=original.isbn)

    def test_rejects_nonimages_tiny_images_and_large_uploads(self):
        for upload in [SimpleUploadedFile("cover.svg", b'<svg onload="alert(1)"/>'), photo(size=(20, 30)),
                       SimpleUploadedFile("big.jpg", b"x" * (4 * 1024 * 1024 + 1))]:
            form = CoverForm({}, {"cover": upload})
            self.assertFalse(form.is_valid())
            self.assertIn("cover", form.errors)
        good = CoverForm({}, {"cover": photo("PNG")})
        self.assertTrue(good.is_valid(), good.errors)

    def test_cover_processing_discards_original_exif(self):
        output = BytesIO()
        original = Image.new("RGB", (300, 400), "blue")
        exif = Image.Exif()
        exif[315] = "Private photographer metadata"
        original.save(output, format="JPEG", exif=exif)
        form = CoverForm({}, {"cover": SimpleUploadedFile("photo.jpg", output.getvalue())})
        self.assertTrue(form.is_valid(), form.errors)
        processed = Image.open(form.cleaned_data["cover"])
        self.assertFalse(processed.getexif())

    def test_no_review_creation_bypass_of_required_isbn_and_cover(self):
        count = Book.objects.count()
        self.assertRedirects(self.client.post(reverse("review_create"), {"book-title": "Sin ISBN", "book-author": "Una Autora", "text": "Opinión", "action": "save"}), reverse("catalog_search"))
        self.assertEqual(Book.objects.count(), count)

    def test_user_record_is_searchable_without_exposing_creator_or_readings(self):
        self.finish(self.details())
        book = Book.objects.get(owner=self.user)
        Review.objects.create(book=book, text="Opinión privada")
        other = self.make_user("searcher@example.com")
        self.client.force_login(other)
        empty = {"items": [], "warnings": [], "total": 0, "has_next": False, "unavailable": True}
        with patch("library.catalog.search", return_value=empty):
            response = self.client.get(reverse("catalog_search"), {"q": "9788408163435"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "La sombra del viento")
        self.assertNotContains(response, self.user.email)
        self.assertNotContains(response, "Opinión privada")
        result = response.context["results"]["items"][0]
        preview = self.client.get(reverse("catalog_preview"), {"selection": result["selection"]})
        self.assertContains(preview, "Ficha aportada por un usuario")
        self.client.post(reverse("catalog_save"), {"selection": preview.context["selection"], "destination": "library"})
        self.assertEqual(Edition.objects.count(), 1)
        self.assertEqual(Book.objects.filter(owner=other).get().catalog_edition_id, book.catalog_edition_id)

    def test_local_and_external_same_isbn_are_one_result(self):
        self.finish(self.details())
        data = edition_data()
        results = {"items": [data], "warnings": [], "total": 1, "has_next": False}
        with patch("library.catalog.search", return_value=results):
            page = self.client.get(reverse("catalog_search"), {"q": data["isbn"]})
        self.assertEqual(page.context["results"]["total"], 1)
        selection = page.context["results"]["items"][0]["selection"]
        with patch("library.catalog.details") as external:
            preview = self.client.get(reverse("catalog_preview"), {"selection": selection})
        external.assert_not_called()
        self.assertContains(preview, "Ficha aportada por un usuario")

    def test_private_legacy_snapshots_are_not_published_as_catalogue_records(self):
        work = Work.objects.create(identity="legacy:Book:1", title="Título privado", author="Autora Privada", origin="legacy")
        Edition.objects.create(work=work, title=work.title, author=work.author, origin="legacy")
        self.assertEqual(work_candidates({"title": work.title, "author": work.author}), [])
        empty = {"items": [], "warnings": [], "total": 0, "has_next": False}
        with patch("library.catalog.search", return_value=empty):
            response = self.client.get(reverse("catalog_search"), {"q": "Título privado"})
        self.assertEqual(response.context["results"]["total"], 0)


class WorkReviewTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.user = self.make_user()
        self.client.force_login(self.user)
        self.edition = store_edition(edition_data())
        self.second = store_edition(edition_data("inventaire", "inv:" + "a" * 32, isbn="9780140328721"))
        self.books = [Book.objects.create(owner=self.user, catalog_edition=e, title=e.title, author=e.author) for e in [self.edition, self.second]]

    def test_cross_provider_editions_share_work_not_edition(self):
        self.assertEqual(self.edition.work_id, self.second.work_id)
        self.assertNotEqual(self.edition.pk, self.second.pk)

    def test_database_allows_only_one_current_review_per_user_and_work(self):
        Review.objects.create(book=self.books[0], text="Mi reseña")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Review.objects.create(book=self.books[1], text="Otra reseña vigente")

    def test_one_private_review_shown_and_edited_from_either_edition(self):
        first, second = self.books
        self.client.post(reverse("review_create") + f"?book={first.pk}", {"text": "Una reseña compartida entre ediciones", "rating": 5, "action": "save"})
        review = Review.objects.get(owner=self.user)
        self.assertEqual(review.work_id, self.edition.work_id)
        self.assertContains(self.client.get(second.get_absolute_url()), review.text)
        self.assertRedirects(self.client.get(reverse("review_create"), {"book": second.pk}), reverse("review_edit", args=[review.pk]))
        self.client.post(reverse("review_edit", args=[review.pk]), {"text": "Opinión actualizada", "action": "save"})
        self.assertEqual(Review.objects.count(), 1)
        for book in self.books:
            self.assertContains(self.client.get(book.get_absolute_url()), "Opinión actualizada")
        other = self.make_user("other@example.com")
        other_book = Book.objects.create(owner=other, catalog_edition=self.second, title="La sombra", author="Carlos Ruiz Zafón")
        self.client.force_login(other)
        self.assertNotContains(self.client.get(other_book.get_absolute_url()), "Opinión actualizada")
        self.assertEqual(self.client.get(reverse("review_edit", args=[review.pk])).status_code, 404)

    def test_notes_stay_on_reading_and_deleting_anchor_keeps_shared_review(self):
        first, second = self.books
        review = Review.objects.create(book=first, text="Conservar reseña")
        ReadingNote.objects.create(book=first, text="Solo en la primera edición", page=10)
        self.assertNotContains(self.client.get(second.get_absolute_url()), "Solo en la primera edición")
        self.client.post(reverse("book_delete", args=[first.pk]))
        review.refresh_from_db()
        self.assertEqual(review.book_id, second.pk)
        self.assertContains(self.client.get(second.get_absolute_url()), "Conservar reseña")

    def test_merge_retains_alias_ids_and_conflicting_reviews_as_history(self):
        duplicate = Work.objects.create(identity="duplicate:1", title=self.edition.title, author=self.edition.author)
        edition = Edition.objects.create(work=duplicate, title=duplicate.title, author=duplicate.author)
        book = Book.objects.create(owner=self.user, catalog_edition=edition, title=edition.title, author=edition.author)
        old = Review.objects.create(book=self.books[0], text="Opinión anterior")
        recent = Review.objects.create(book=book, text="Opinión más reciente")
        root = merge_works([self.edition.work, duplicate])
        old.refresh_from_db(); recent.refresh_from_db(); duplicate.refresh_from_db(); edition.refresh_from_db()
        self.assertEqual(Review.objects.count(), 2)
        self.assertFalse(old.is_current)
        self.assertTrue(recent.is_current)
        self.assertEqual(old.work_id, recent.work_id)
        self.assertEqual(edition.work_id, root.pk)
        self.assertEqual(duplicate.merged_into_id, root.pk)
        self.assertContains(self.client.get(self.books[0].get_absolute_url()), "Reseñas anteriores conservadas")

    def test_conflicting_volumes_do_not_share_work(self):
        data = edition_data("inventaire", "inv:" + "b" * 32, isbn="9780307474728")
        data.update(title="La sombra del viento, tomo 2", work_key="wd:Q12345")
        third = store_edition(data)
        self.assertNotEqual(third.work_id, self.edition.work_id)
