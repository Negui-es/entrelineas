from unittest.mock import patch
from django.core import mail
from django.test import override_settings
from django.urls import resolve, reverse
from django.utils import translation
from .forms import BookForm
from .models import Book, Review
from .tests import AppTestCase
from entrelineas.localization import language_navigation


@override_settings(DEBUG=False, SECURE_SSL_REDIRECT=False)
class LocalizationTests(AppTestCase):
    def setUp(self):
        super().setUp()
        translation.activate("es")
        self.addCleanup(translation.activate, "es")

    def test_root_negotiates_browser_language_and_has_no_cache(self):
        for header, language in [("de-DE,de;q=0.9,en;q=0.7", "de"), ("it-IT", "it"),
                                 ("fr-CA,en;q=0.5", "fr"), ("ja,en;q=0.8", "en"), ("ja,zh", "es")]:
            response = self.client.get("/", HTTP_ACCEPT_LANGUAGE=header)
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.headers["Location"], f"/{language}/")
            self.assertIn("Accept-Language", response.headers["Vary"])
            self.assertIn("no-store", response.headers["Cache-Control"])

    def test_all_languages_have_localized_paths_login_and_form_labels(self):
        for code, slug, heading, author in [
            ("es", "biblioteca", "Iniciar sesión", "Autor o autora"),
            ("en", "library", "Sign in", "Author"),
            ("de", "bibliothek", "Anmelden", "Autor"),
            ("fr", "bibliotheque", "Se connecter", "Auteur"),
            ("it", "biblioteca", "Accedi", "Autore")]:
            with self.subTest(language=code), translation.override(code):
                self.assertEqual(reverse("library"), f"/{code}/{slug}/")
                response = self.client.get(reverse("account_login"), HTTP_ACCEPT_LANGUAGE="es")
                self.assertContains(response, f'lang="{code}"')
                self.assertContains(response, heading)
                self.assertEqual(response.headers["Content-Language"], code)
                self.assertEqual(str(BookForm().fields["author"].label), author)

    def test_switch_preserves_book_query_and_uses_translated_route(self):
        user = self.make_user()
        book = Book.objects.create(owner=user, title="El libro", author="Autora")
        self.client.force_login(user)
        response = self.client.get(f"/en/books/{book.pk}/?page=2")
        links = response.context["language_links"]
        german = next(link for link in links if link["code"] == "de")
        self.assertEqual(german["url"], f"/de/buecher/{book.pk}/?page=2")
        self.assertContains(response, "El libro")  # User content stays untouched.

    def test_legacy_links_keep_ids_query_and_tokens(self):
        response = self.client.get("/libros/42/?q=abc", HTTP_ACCEPT_LANGUAGE="en")
        self.assertEqual(response.headers["Location"], "/en/books/42/?q=abc")
        response = self.client.get("/lista/a-secret-token/", HTTP_ACCEPT_LANGUAGE="fr")
        self.assertEqual(response.headers["Location"], "/fr/liste/a-secret-token/")
        response = self.client.get("/acceso/confirm-email/abc:signature/", HTTP_ACCEPT_LANGUAGE="it")
        self.assertEqual(response.headers["Location"], "/it/accesso/conferma-email/abc:signature/")

    def test_legacy_post_redirect_preserves_method(self):
        response = self.client.post("/buscar/guardar/", {"selection": "test"}, HTTP_ACCEPT_LANGUAGE="en")
        self.assertEqual(response.status_code, 307)
        self.assertEqual(response.headers["Location"], "/en/search/save/")

    def test_password_token_with_hyphens_round_trips_in_every_language(self):
        for code in ("es", "en", "de", "fr", "it"):
            with translation.override(code):
                url = reverse("account_reset_password_from_key", kwargs={"uidb36": "abc12", "key": "token-with-hyphens"})
                self.assertEqual(resolve(url).kwargs, {"uidb36": "abc12", "key": "token-with-hyphens"})

    def test_reset_email_uses_requested_language_and_localized_url(self):
        user = self.make_user()
        with translation.override("en"):
            response = self.client.post(reverse("account_reset_password"), {"email": user.email})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/en/account/password/", mail.outbox[0].body)
        self.assertNotIn("/acceso/", mail.outbox[0].body)

    def test_errors_and_javascript_are_localized(self):
        from entrelineas import errors
        for code, phrase in [("en", "The narrator has lost the plot."), ("de", "Der Erzähler hat den Faden verloren."),
                             ("fr", "Le narrateur a perdu le fil."), ("it", "Il narratore ha perso il filo.")]:
            with translation.override(code), patch.object(errors, "choice", return_value=errors.MESSAGES[500][0]):
                response = errors.server_error(__import__('django.test',fromlist=['RequestFactory']).RequestFactory().get(f"/{code}/"))
                self.assertContains(response, phrase, status_code=500)
                response = self.client.get(reverse("javascript-catalog"))
                self.assertContains(response, "gettext")
        response = self.client.get("/fr/page-inconnue/", HTTP_ACCEPT_LANGUAGE="en")
        self.assertContains(response, 'lang="fr"', status_code=404)
        self.assertContains(response, "Page introuvable", status_code=404)

    def test_health_endpoint_and_ownership_are_not_changed(self):
        self.assertEqual(self.client.get("/salud/").status_code, 200)
        owner = self.make_user("owner@example.com")
        other = self.make_user("other@example.com")
        book = Book.objects.create(owner=owner, title="Private book", author="Author")
        self.client.force_login(other)
        response = self.client.get(f"/en/books/{book.pk}/")
        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, "Private book", status_code=404)
