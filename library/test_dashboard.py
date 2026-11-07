from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.urls import reverse
from django.utils import translation

from .models import Book, Edition, Review, Work
from .tests import AppTestCase


class DashboardTests(AppTestCase):
    def setUp(self):
        super().setUp()
        translation.activate("es")
        self.user = self.make_user()
        self.client.force_login(self.user)
        self.today = patch("library.dashboard.timezone.localdate", return_value=date(2026, 10, 26))
        self.today.start()
        self.addCleanup(self.today.stop)

    def book(self, **kwargs):
        return Book.objects.create(owner=self.user, title="Una historia", author="Autora", **kwargs)

    def test_home_empty_and_reviews_have_separate_routes(self):
        response = self.client.get(reverse("home"))
        self.assertContains(response, "Añadir mi primer libro")
        self.assertNotContains(response, 'class="home-metrics"')
        self.assertNotEqual(reverse("home"), reverse("reviews"))
        self.assertContains(self.client.get(reverse("reviews")), "Aún no tienes reseñas")
        self.assertContains(response, 'aria-current="page"')
        self.assertIn("no-store", response.headers["Cache-Control"])

    def test_year_counts_dates_status_pages_and_owner(self):
        edition = Edition.objects.create(work=Work.objects.create(identity="isbn:test", title="Catálogo", author="Autora"),
                                         title="Catálogo", author="Autora", total_pages=220)
        self.book(status="finished", finished_at=date(2026, 2, 10), started_at=date(2026, 2, 1),
                  total_pages=100, catalog_edition=edition)
        self.book(status="finished", finished_at=date(2026, 10, 26), total_pages=80)
        self.book(status="finished")
        self.book(status="finished", finished_at=date(2025, 1, 1), total_pages=900)
        self.book(status="finished", finished_at=date(2026, 12, 1), total_pages=800)
        self.book(status="pending", finished_at=date(2026, 4, 1), total_pages=700)
        other = self.make_user("other@example.com")
        Book.objects.create(owner=other, title="Secreto ajeno", author="Otra", status="finished", finished_at=date(2026, 3, 2))
        response = self.client.get(reverse("home"))
        self.assertEqual(response.context["year_count"], 2)
        self.assertEqual(response.context["year_pages"], 300)
        self.assertEqual(response.context["undated_count"], 1)
        self.assertEqual(response.context["average_days"], 10)
        self.assertEqual(response.context["pace"], .2)
        self.assertEqual(response.context["stats"]["total"], 6)
        self.assertEqual([m["count"] for m in response.context["months"]], [0, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0])
        self.assertNotContains(response, "Secreto ajeno")

    def test_saved_favorites_and_current_reviews_only(self):
        book = self.book(status="finished")
        review = Review.objects.create(book=book, rating=Decimal("4.5"), favorite=True, is_draft=False)
        Review.objects.create(book=self.book(), rating=1, favorite=True, is_draft=True)
        Review.objects.create(book=self.book(), rating=2, is_current=False, is_draft=False)
        response = self.client.get(reverse("home"))
        self.assertEqual(response.context["review_count"], 2)
        self.assertEqual(response.context["average_rating"], Decimal("4.5"))
        self.assertEqual(list(response.context["favorites"]), [review])
        self.assertIsNone(response.context["review_prompt"])

    def test_review_prompt_uses_existing_book_and_shared_work_review(self):
        book = self.book(status="finished")
        response = self.client.get(reverse("home"))
        self.assertContains(response, f'{reverse("review_create")}?book={book.pk}')
        work = Work.objects.create(identity="test:shared", title="Compartido", author="Autora")
        edition = Edition.objects.create(work=work, title="Compartido", author="Autora")
        book.catalog_edition = edition
        book.save()
        Review.objects.create(book=self.book(catalog_edition=edition), is_draft=False)
        self.assertIsNone(self.client.get(reverse("home")).context["review_prompt"])

    def test_all_locales_render_and_navigation_points_home(self):
        self.book(status="reading", total_pages=100, current_page=25)
        for language in ("es", "en", "de", "fr", "it"):
            with self.subTest(language=language), translation.override(language):
                response = self.client.get(reverse("home"))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, f'lang="{language}"')
                self.assertContains(response, f'href="/{language}/"')
                self.assertContains(response, '<progress value="25" max="100"')
                self.assertContains(self.client.get(reverse("reviews")), f'href="/{language}/"')

    def test_authentication_and_verification_required(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("home")).status_code, 302)
        unverified = self.make_user("unverified@example.com", verified=False)
        self.client.force_login(unverified)
        response = self.client.get(reverse("home"))
        self.assertTemplateUsed(response, "account/verified_email_required.html")
        self.assertNotContains(response, 'class="home-metrics"')
