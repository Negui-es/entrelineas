from datetime import timedelta

from django.urls import reverse
from django.test import override_settings
from django.utils import timezone

from .models import Book, Review, Wishlist, WishItem
from .tests import AppTestCase


@override_settings(SECURE_SSL_REDIRECT=False)
class PanelTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.user = self.make_user()
        self.client.force_login(self.user)
        listing = Wishlist.objects.create(owner=self.user)
        self.books, self.reviews, self.wishes = [], [], []
        for number in range(25):
            book = Book.objects.create(owner=self.user, title=f"Libro {number:02}", author="Autora")
            self.books.append(book)
            self.reviews.append(Review.objects.create(owner=self.user, book=book, favorite=True))
            self.wishes.append(WishItem.objects.create(wishlist=listing, title=book.title, author=book.author))

    def test_panels_have_full_pages_and_no_missing_or_repeated_results(self):
        for route, records in (("reviews", self.reviews), ("library", self.books), ("wishlist", self.wishes)):
            with self.subTest(panel=route):
                # Equal timestamps require a stable secondary order across pages.
                type(records[0]).objects.filter(pk__in=[item.pk for item in records]).update(created_at=timezone.now())
                ids = []
                for number, count in ((1, 12), (2, 12), (3, 1)):
                    response = self.client.get(reverse(route), {"page": number})
                    self.assertEqual(response.status_code, 200)
                    page = response.context["page_obj"]
                    self.assertEqual(len(page), count)
                    ids.extend(item.pk for item in page)
                    self.assertContains(response, "data-panel-grid")
                    self.assertContains(response, "data-panel-pagination")
                self.assertEqual(ids, [item.pk for item in reversed(records)])

    def test_creation_date_takes_priority_over_edits_and_primary_key(self):
        for route, records in (("reviews", self.reviews), ("library", self.books), ("wishlist", self.wishes)):
            with self.subTest(panel=route):
                model = type(records[0])
                oldest_pk = records[0].pk
                model.objects.filter(pk=oldest_pk).update(created_at=timezone.now() + timedelta(days=1))
                if route != "wishlist":
                    model.objects.filter(pk=records[-1].pk).update(updated_at=timezone.now() + timedelta(days=2))
                response = self.client.get(reverse(route))
                self.assertEqual(response.context["page_obj"][0].pk, oldest_pk)

    def test_next_links_preserve_search_and_filters_and_stop_at_the_end(self):
        for route, params in (("reviews", {"filter": "favorites"}), ("library", {"status": "pending"}), ("wishlist", {})):
            with self.subTest(panel=route):
                params = {**params, "q": "Libro"}
                response = self.client.get(reverse(route), params)
                self.assertContains(response, 'rel="next"')
                self.assertContains(response, "q=Libro")
                for key, value in params.items():
                    self.assertContains(response, f"{key}={value}")
                last = self.client.get(reverse(route), {**params, "page": 3})
                self.assertNotContains(last, 'rel="next"')

    def test_other_users_results_are_excluded_from_every_page(self):
        other = self.make_user("other@example.com")
        book = Book.objects.create(owner=other, title="Solo otra cuenta", author="Otra")
        Review.objects.create(owner=other, book=book)
        WishItem.objects.create(wishlist=Wishlist.objects.create(owner=other), title=book.title, author=book.author)
        for route in ("reviews", "library", "wishlist"):
            response = self.client.get(reverse(route), {"page": 2})
            self.assertEqual(response.context["page_obj"].paginator.count, 25)
            self.assertNotContains(response, "Solo otra cuenta")
