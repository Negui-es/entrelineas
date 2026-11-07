from copy import deepcopy
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from accounts.models import User
from .document_import import import_manifest
from .forms import ReviewForm
from .models import Book, DocumentImportEntry, Review
from .templatetags.library_tags import stars


class DocumentImportTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="word@example.com", display_name="Lector")
        self.row = dict(source_key="test:1", title="Libro", author="Autora", status="finished",
                        started_at="2024-01-01", finished_at="2024-03-01", rating="4.25",
                        text="Texto original\n\nSegundo párrafo", contains_spoilers=True)
        self.manifest = dict(owner_id=self.user.pk, existing_rating_policy="keep_web", books=[self.row])

    def test_preview_does_not_write_and_apply_is_idempotent(self):
        import_manifest(self.user, self.manifest)
        self.assertFalse(Book.objects.exists())
        import_manifest(self.user, self.manifest, apply=True)
        review = Review.objects.get()
        self.assertEqual(review.rating, Decimal("4.25"))
        self.assertEqual(review.text, self.row["text"])
        self.assertTrue(review.contains_spoilers)
        self.assertEqual(review.book.finished_at.isoformat(), "2024-03-01")
        before = review.updated_at
        result = import_manifest(self.user, self.manifest, apply=True)
        review.refresh_from_db()
        self.assertEqual(result[0]["action"], "already_imported")
        self.assertEqual(review.updated_at, before)
        self.assertEqual(Book.objects.count(), 1)

    def test_existing_review_text_rating_and_personal_fields_survive(self):
        book = Book.objects.create(owner=self.user, title="Libro", author="Autora")
        review = Review.objects.create(book=book, owner=self.user, rating=5, text="Versión ampliada",
                                       best="Lo mejor", favorite=True)
        self.row["existing_book_id"] = book.pk
        import_manifest(self.user, self.manifest, apply=True)
        review.refresh_from_db()
        self.assertEqual(review.rating, 5)
        self.assertTrue(review.text.startswith("Versión ampliada"))
        self.assertIn(self.row["text"], review.text)
        self.assertEqual(review.best, "Lo mejor")
        self.assertTrue(review.favorite)
        self.assertEqual(Book.objects.count(), 1)

    def test_ownership_failure_rolls_back_entire_import(self):
        other = User.objects.create_user(email="other@example.com", display_name="Otro")
        book = Book.objects.create(owner=other, title="Libro", author="Autora")
        second = deepcopy(self.row)
        second.update(source_key="test:2", existing_book_id=book.pk)
        self.manifest["books"].append(second)
        with self.assertRaises(ValidationError):
            import_manifest(self.user, self.manifest, apply=True)
        self.assertFalse(Book.objects.filter(owner=self.user).exists())
        self.assertFalse(DocumentImportEntry.objects.exists())

    def test_unfinished_books_have_no_finished_date_or_empty_review(self):
        self.row.update(status="reading", finished_at=None, text="", rating=None)
        import_manifest(self.user, self.manifest, apply=True)
        self.assertIsNone(Book.objects.get().finished_at)
        self.assertFalse(Review.objects.exists())

    def test_fractional_rating_form_display_and_database_range(self):
        for value in ("0.5", "3.5", "4.25", "5"):
            form = ReviewForm(data={"rating": value, "text": "Opinión"})
            self.assertTrue(form.is_valid(), form.errors)
        for value in ("0", "5.1", "4.251"):
            self.assertFalse(ReviewForm(data={"rating": value}).is_valid())
        self.assertIn("85.00%", stars(Decimal("4.25")))
        book = Book.objects.create(owner=self.user, title="Libro", author="Autora")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Review.objects.create(book=book, owner=self.user, rating=Decimal("5.1"))
