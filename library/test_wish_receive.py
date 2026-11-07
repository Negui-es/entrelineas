import uuid
from unittest.mock import patch

from django.test import Client, override_settings
from django.urls import reverse

from .catalog_store import store_edition
from .models import Book, CSVImportEntry, GoodreadsEntry, ReadingNote, Review, Wishlist, WishItem
from .test_catalog import edition_data
from .tests import AppTestCase


@override_settings(SECURE_SSL_REDIRECT=False)
class ReceiveWishTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.user = self.make_user()
        self.client.force_login(self.user)
        self.listing = Wishlist.objects.create(owner=self.user)
        self.wish = WishItem.objects.create(wishlist=self.listing, title="Un regalo", author="Una Autora", color="rose", edition="En inglés, en papel")
        self.url = reverse("wish_receive", args=[self.wish.pk])

    def test_unlinked_wish_moves_to_pending_library_with_preferences(self):
        self.assertContains(self.client.get(reverse("wishlist")), self.url)
        self.assertRedirects(self.client.post(self.url), reverse("wishlist"))
        self.assertFalse(WishItem.objects.filter(pk=self.wish.pk).exists())
        book = Book.objects.get()
        self.assertEqual((book.title, book.author, book.color, book.status), ("Un regalo", "Una Autora", "rose", "pending"))
        self.assertEqual(book.current_page, 0)
        self.assertEqual(book.owner, self.user)
        self.assertIn("En inglés, en papel", ReadingNote.objects.get(book=book).text)
        self.assertEqual(self.client.post(self.url).status_code, 404)
        self.assertEqual(Book.objects.count(), 1)
        self.assertEqual(ReadingNote.objects.count(), 1)

    def test_linked_wish_retains_edition_cover_and_pages(self):
        edition = store_edition(edition_data())
        self.wish.catalog_edition = edition
        self.wish.save()
        self.client.post(self.url)
        book = Book.objects.get()
        self.assertEqual(book.catalog_edition, edition)
        self.assertEqual(book.cover_url, edition.display_cover_url)
        self.assertEqual(book.total_pages, edition.total_pages)
        self.assertEqual(book.isbn, edition.isbn)

    def test_existing_reading_and_review_are_preserved(self):
        edition = store_edition(edition_data())
        self.wish.catalog_edition = edition
        self.wish.save()
        book = Book.objects.create(owner=self.user, catalog_edition=edition, title=edition.title, author=edition.author,
                                   status="reading", current_page=50, total_pages=592)
        review = Review.objects.create(book=book, owner=self.user, rating=4, text="Mi opinión")
        self.client.post(self.url)
        self.assertEqual(Book.objects.count(), 1)
        book.refresh_from_db()
        review.refresh_from_db()
        self.assertEqual((book.status, book.current_page), ("reading", 50))
        self.assertEqual((review.text, review.rating), ("Mi opinión", 4))

    def test_import_provenance_moves_to_book_instead_of_being_deleted(self):
        goodreads = GoodreadsEntry.objects.create(owner=self.user, external_id="123", wish=self.wish)
        native = CSVImportEntry.objects.create(owner=self.user, source_id=uuid.uuid4(), wish=self.wish)
        self.client.post(self.url)
        for entry in (goodreads, native):
            entry.refresh_from_db()
            self.assertIsNone(entry.wish_id)
            self.assertEqual(entry.book_id, Book.objects.get().pk)

    def test_private_request_requires_owner_verified_email_post_and_csrf(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.assertTrue(WishItem.objects.filter(pk=self.wish.pk).exists())
        self.assertEqual(Client().post(self.url).status_code, 302)
        other = self.make_user("other@example.com")
        self.client.force_login(other)
        self.assertEqual(self.client.post(self.url).status_code, 404)
        self.client.force_login(self.make_user("unverified@example.com", verified=False))
        self.assertTemplateUsed(self.client.post(self.url), "account/verified_email_required.html")
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        self.assertEqual(csrf_client.post(self.url).status_code, 403)
        self.assertEqual(Book.objects.count(), 0)
        self.listing.enable_sharing()
        public = Client().get(reverse("wishlist_shared", args=[self.listing.share_token]))
        self.assertNotContains(public, self.url)

    def test_failure_rolls_back_both_sides_of_move(self):
        with patch("library.views.ReadingNote.objects.create", side_effect=RuntimeError("save failed")):
            with self.assertRaises(RuntimeError):
                self.client.post(self.url)
        self.assertEqual(Book.objects.count(), 0)
        self.assertTrue(WishItem.objects.filter(pk=self.wish.pk).exists())

    def test_same_title_in_a_different_known_edition_stays_separate(self):
        first = store_edition(edition_data())
        second = store_edition(edition_data(external_id="OL99M", isbn="9780140328721", pages=96))
        Book.objects.create(owner=self.user, title=first.title, author=first.author, catalog_edition=first, status="finished")
        self.wish.catalog_edition = second
        self.wish.save()
        self.client.post(self.url)
        self.assertEqual(Book.objects.count(), 2)
        self.assertEqual(Book.objects.get(catalog_edition=second).status, "pending")
