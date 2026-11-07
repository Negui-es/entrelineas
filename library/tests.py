import re
from datetime import date

from allauth.account.models import EmailAddress
from django.core import mail
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from .forms import BookForm, WishForm
from .models import Book, ReadingNote, Review, Wishlist, WishItem

TEST_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
    STORAGES=TEST_STORAGES,
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class AppTestCase(TestCase):
    def setUp(self):
        cache.clear()

    def make_user(self, email="lector@example.com", verified=True):
        user = User.objects.create_user(email=email, password="Lecturas-divertidas-826!", display_name="Lector")
        EmailAddress.objects.create(user=user, email=user.email, primary=True, verified=verified)
        return user


class AuthenticationTests(AppTestCase):
    def test_registration_is_closed_and_no_signup_option_is_displayed(self):
        response = self.client.get(reverse("account_login"))
        self.assertNotContains(response, reverse("account_signup"))
        response = self.client.get(reverse("account_signup"))
        self.assertTemplateUsed(response, "account/signup_closed.html")
        self.assertNotContains(response, 'name="password1"')
        before = User.objects.count()
        response = self.client.post(reverse("account_signup"), {
            "display_name": "Nueva", "email": "nueva@example.com",
            "password1": "Una-biblioteca-luminosa-82!", "password2": "Una-biblioteca-luminosa-82!",
        })
        self.assertTemplateUsed(response, "account/signup_closed.html")
        self.assertEqual(User.objects.count(), before)
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(REGISTRATION_OPEN=True)
    def test_signup_requires_email_confirmation_before_library_access(self):
        response = self.client.post(reverse("account_signup"), {
            "display_name": "Ana", "email": "Ana@Example.com",
            "password1": "Una-biblioteca-luminosa-82!", "password2": "Una-biblioteca-luminosa-82!",
        })
        self.assertRedirects(response, reverse("account_email_verification_sent"))
        user = User.objects.get(email="ana@example.com")
        self.assertEqual(user.display_name, "Ana")
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertFalse(EmailAddress.objects.get(user=user).verified)
        self.assertEqual(len(mail.outbox), 1)
        link = re.search(r"http://testserver(/\S+)", mail.outbox[0].body).group(1)
        self.assertEqual(self.client.get(link).status_code, 200)
        self.assertFalse(EmailAddress.objects.get(user=user).verified, "GET must not confirm an email")
        self.client.post(link)
        self.assertTrue(EmailAddress.objects.get(user=user).verified)
        response = self.client.post(reverse("account_login"), {"login": user.email, "password": "Una-biblioteca-luminosa-82!"})
        self.assertRedirects(response, reverse("home"))
        self.assertContains(self.client.get(reverse("reviews")), "Aún no tienes reseñas")

    def test_anonymous_and_unverified_users_cannot_read_books(self):
        user = self.make_user(verified=False)
        book = Book.objects.create(owner=user, title="Libro privado", author="Autora")
        response = self.client.get(book.get_absolute_url())
        self.assertEqual(response.status_code, 302)
        self.client.force_login(user)
        response = self.client.get(book.get_absolute_url())
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "account/verified_email_required.html")
        self.assertNotContains(response, "Libro privado")
        self.assertNotContains(self.client.get(reverse("account_email_verification_sent")), "Libro privado")

    def test_password_recovery_sends_usable_link_and_changes_password(self):
        user = self.make_user()
        response = self.client.post(reverse("account_reset_password"), {"email": user.email})
        self.assertRedirects(response, reverse("account_reset_password_done"))
        self.assertEqual(len(mail.outbox), 1)
        link = re.search(r"http://testserver(/\S+)", mail.outbox[0].body).group(1)
        response = self.client.get(link, follow=True)
        self.assertContains(response, "Una nueva contraseña")
        target = response.request["PATH_INFO"]
        self.client.post(target, {"password1": "Otra-clave-lectora-957!", "password2": "Otra-clave-lectora-957!"}, follow=True)
        user.refresh_from_db()
        self.assertTrue(user.check_password("Otra-clave-lectora-957!"))

    def test_email_is_case_insensitive_and_logout_requires_post(self):
        user = self.make_user(email="LECTOR@Example.com")
        self.assertEqual(user.email, "lector@example.com")
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_user(email="Lector@example.com", password="Otra-clave-828!", display_name="Otro")
        self.client.force_login(user)
        self.client.get(reverse("account_logout"))
        self.assertIn("_auth_user_id", self.client.session)
        self.client.post(reverse("account_logout"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_profile_and_password_change_are_usable(self):
        user = self.make_user()
        self.client.force_login(user)
        self.assertContains(self.client.get(reverse("profile")), 'name="display_name"')
        self.client.post(reverse("profile"), {"display_name": "María"})
        user.refresh_from_db()
        self.assertEqual(user.display_name, "María")
        self.assertContains(self.client.get(reverse("account_change_password")), "Cambiar contraseña")
        self.assertContains(self.client.get(reverse("account_email")), user.email)


class ReadingTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.user = self.make_user()
        self.client.force_login(self.user)
        self.book = Book.objects.create(owner=self.user, title="El libro", author="La autora", total_pages=200, status="reading")

    def test_create_review_on_selected_book_then_edit(self):
        data = {
            "book-title": "Un libro nuevo", "book-author": "Autora nueva", "book-color": "blue",
            "book-status": "finished", "book-current_page": 0,
            "rating": 5, "text": "Una historia para volver.", "favorite": "on", "action": "save",
        }
        response = self.client.post(reverse("review_create") + f"?book={self.book.pk}", data)
        review = Review.objects.get(book=self.book)
        self.assertRedirects(response, review.book.get_absolute_url())
        self.assertFalse(review.is_draft)
        self.assertTrue(review.favorite)
        self.assertEqual(review.visibility, "private")
        self.assertEqual(review.book.owner, self.user)
        self.client.post(reverse("review_edit", args=[review.pk]), {"text": "Otra opinión.", "rating": 4, "action": "save", "visibility": "public"})
        review.refresh_from_db()
        self.assertEqual(review.text, "Otra opinión.")
        self.assertEqual(review.visibility, "private")

    def test_invalid_review_does_not_leave_orphan_book(self):
        count = Book.objects.count()
        response = self.client.post(reverse("review_create") + f"?book={self.book.pk}", {
            "book-title": "Sin opinión", "book-author": "Autor", "book-color": "gold",
            "book-status": "finished", "book-current_page": 0, "rating": 5, "action": "save",
        })
        self.assertContains(response, "Escribe al menos una idea")
        self.assertEqual(Book.objects.count(), count)

    def test_empty_draft_on_existing_book_and_duplicate_route(self):
        url = reverse("review_create") + f"?book={self.book.pk}"
        self.client.post(url, {"action": "draft"})
        review = Review.objects.get(book=self.book)
        self.assertTrue(review.is_draft)
        self.assertIsNone(review.rating)
        self.assertRedirects(self.client.get(url), reverse("review_edit", args=[review.pk]))
        self.assertEqual(self.client.get(reverse("review_create"), {"book": "no-es-un-id"}).status_code, 404)

    def test_search_filters_favorites_and_drafts(self):
        review = Review.objects.create(book=self.book, text="Una joya", rating=4, is_draft=False)
        self.assertContains(self.client.get(reverse("reviews"), {"q": "joya"}), "El libro")
        self.assertNotContains(self.client.get(reverse("reviews"), {"q": "inexistente"}), 'aria-label="Leer mi reseña de El libro"')
        self.assertNotContains(self.client.get(reverse("reviews"), {"filter": "drafts"}), 'aria-label="Leer mi reseña de El libro"')
        self.assertEqual(self.client.get(reverse("favorite", args=[review.pk])).status_code, 405)
        self.client.post(reverse("favorite", args=[review.pk]))
        self.assertContains(self.client.get(reverse("reviews"), {"filter": "favorites"}), 'aria-label="Leer mi reseña de El libro"')

    def test_spoilers_are_hidden_on_cards_and_escaped_in_detail(self):
        Review.objects.create(book=self.book, text='El final secreto <script>alert("x")</script>', contains_spoilers=True, is_draft=False)
        home = self.client.get(reverse("reviews"))
        self.assertNotContains(home, "El final secreto")
        detail = self.client.get(self.book.get_absolute_url())
        self.assertContains(detail, "Esta reseña contiene spoilers")
        self.assertContains(detail, "&lt;script&gt;")
        self.assertNotContains(detail, '<script>alert("x")</script>')

    def test_private_notes_and_page_validation(self):
        url = reverse("note_add", args=[self.book.pk])
        self.assertEqual(self.client.post(url, {"text": "Mi secreto", "page": 201}).status_code, 400)
        self.assertEqual(ReadingNote.objects.count(), 0)
        self.client.post(url, {"text": "Mi secreto", "page": 112})
        note = ReadingNote.objects.get(book=self.book)
        self.assertEqual(note.text, "Mi secreto")
        self.assertContains(self.client.get(self.book.get_absolute_url()), "Mi secreto")
        self.assertEqual(self.client.get(reverse("note_delete", args=[note.pk])).status_code, 405)
        self.client.post(reverse("note_delete", args=[note.pk]))
        self.assertEqual(ReadingNote.objects.count(), 0)

    def test_book_forms_validate_progress_and_dates(self):
        data = {"title": "Libro", "author": "Autor", "color": "gold", "status": "reading", "total_pages": 100, "current_page": 101}
        form = BookForm(data)
        self.assertFalse(form.is_valid())
        self.assertIn("current_page", form.errors)
        data.update(current_page=40, started_at="2026-10-20", finished_at="2026-10-10")
        form = BookForm(data)
        self.assertFalse(form.is_valid())
        self.assertIn("finished_at", form.errors)
        data["finished_at"] = "2026-10-25"
        self.assertTrue(BookForm(data).is_valid())

    def test_edit_book_library_filter_and_delete_cascade(self):
        review = Review.objects.create(book=self.book, text="Una historia")
        ReadingNote.objects.create(book=self.book, text="Nota")
        self.assertContains(self.client.get(reverse("library"), {"status": "reading"}), "El libro")
        self.assertEqual(self.client.get(reverse("book_edit", args=[self.book.pk])).status_code, 200)
        self.client.post(reverse("book_edit", args=[self.book.pk]), {"title": "Otro título", "author": "La autora", "status": "finished", "color": "blue", "current_page": 200, "total_pages": 200})
        self.book.refresh_from_db()
        self.assertEqual(self.book.title, "Otro título")
        self.client.get(reverse("book_delete", args=[self.book.pk]))
        self.assertTrue(Book.objects.filter(pk=self.book.pk).exists())
        self.client.post(reverse("book_delete", args=[self.book.pk]))
        self.assertFalse(Book.objects.filter(pk=self.book.pk).exists())
        self.assertFalse(Review.objects.filter(pk=review.pk).exists())
        self.assertEqual(ReadingNote.objects.count(), 0)

    def test_csrf_is_required_for_writes(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        review = Review.objects.create(book=self.book)
        self.assertEqual(csrf_client.post(reverse("favorite", args=[review.pk])).status_code, 403)
        self.assertEqual(csrf_client.post(reverse("wishlist_sharing"), {"action": "enable"}).status_code, 403)

    def test_private_responses_cannot_be_cached(self):
        response = self.client.get(reverse("reviews"))
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertEqual(response.headers["X-Robots-Tag"], "noindex, nofollow")
        self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])


class IsolationTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.owner = self.make_user()
        self.other = self.make_user("otra@example.com")
        self.book = Book.objects.create(owner=self.owner, title="TÍTULO PRIVADO ÚNICO", author="Autora")
        self.review = Review.objects.create(book=self.book, text="OPINIÓN SECRETA")
        self.note = ReadingNote.objects.create(book=self.book, text="NOTA SECRETA")
        self.listing = Wishlist.objects.create(owner=self.owner)
        self.wish = WishItem.objects.create(wishlist=self.listing, title="Deseo privado", author="Autora")
        self.client.force_login(self.other)

    def test_other_users_cannot_read_edit_or_delete_owned_data(self):
        get_urls = [
            self.book.get_absolute_url(), reverse("book_edit", args=[self.book.pk]),
            reverse("book_delete", args=[self.book.pk]), reverse("review_edit", args=[self.review.pk]),
            reverse("review_create") + f"?book={self.book.pk}",
            reverse("wish_edit", args=[self.wish.pk]), reverse("wish_delete", args=[self.wish.pk]),
        ]
        for url in get_urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)
                self.assertEqual(self.client.post(url, {"text": "Ataque", "action": "save"}).status_code, 404)
        for name, pk in [("favorite", self.review.pk), ("note_delete", self.note.pk), ("note_add", self.book.pk)]:
            self.assertEqual(self.client.post(reverse(name, args=[pk]), {"text": "Ataque"}).status_code, 404)
        self.assertEqual(Review.objects.get(pk=self.review.pk).text, "OPINIÓN SECRETA")
        self.assertTrue(ReadingNote.objects.filter(pk=self.note.pk).exists())

    def test_other_users_cannot_search_foreign_content(self):
        for name in ["reviews", "library", "wishlist"]:
            response = self.client.get(reverse(name), {"q": "PRIVADO"})
            self.assertNotContains(response, self.book.title)
            self.assertNotContains(response, self.review.text)
            self.assertNotContains(response, self.wish.title)

    def test_shared_list_only_contains_explicit_wishlist_fields_and_revokes(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse("wishlist_sharing")).status_code, 405)
        self.client.post(reverse("wishlist_sharing"), {"action": "enable"})
        self.listing.refresh_from_db()
        token = self.listing.share_token
        public = Client()
        url = reverse("wishlist_shared", args=[token])
        response = public.get(url)
        self.assertContains(response, self.wish.title)
        for secret in [self.owner.email, self.book.title, self.review.text, self.note.text]:
            self.assertNotContains(response, secret)
        self.assertNotContains(response, reverse("wish_edit", args=[self.wish.pk]))
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.client.post(reverse("wishlist_sharing"), {"action": "revoke"})
        self.assertEqual(public.get(url).status_code, 404)
        self.client.post(reverse("wishlist_sharing"), {"action": "enable"})
        self.listing.refresh_from_db()
        self.assertNotEqual(token, self.listing.share_token)
        self.assertEqual(public.get(url).status_code, 404)

    def test_wishlist_is_private_until_shared_and_validates_purchase_urls(self):
        self.assertIsNone(self.listing.share_token)
        self.assertEqual(Client().get(reverse("wishlist_shared", args=["random-token"])).status_code, 404)
        self.assertFalse(WishForm({"title": "Libro", "author": "Autor", "color": "blue", "priority": "high", "purchase_url": "javascript:alert(1)"}).is_valid())
        self.client.force_login(self.owner)
        self.client.post(reverse("wish_create"), {"title": "Otro deseo", "author": "Autora", "color": "rose", "priority": "high", "edition": "Tapa dura", "purchase_url": "https://example.com/libro"})
        item = WishItem.objects.get(title="Otro deseo")
        self.assertEqual(item.wishlist.owner, self.owner)
        self.assertEqual(item.edition, "Tapa dura")
        self.assertContains(self.client.get(reverse("wishlist")), item.title)
        self.client.post(reverse("wish_delete", args=[item.pk]))
        self.assertFalse(WishItem.objects.filter(pk=item.pk).exists())
