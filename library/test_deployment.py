from django.test import Client, override_settings
from django.urls import reverse
from .tests import AppTestCase


@override_settings(
    DEBUG=False,
    ALLOWED_HOSTS=["entrelineas.negui.es", "127.0.0.1"],
    CSRF_TRUSTED_ORIGINS=["https://entrelineas.negui.es"],
    SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
    SECURE_SSL_REDIRECT=True,
    SESSION_COOKIE_SECURE=True,
    CSRF_COOKIE_SECURE=True,
    REGISTRATION_OPEN=False,
)
class TunnelDeploymentTests(AppTestCase):
    def test_https_tunnel_does_not_loop_and_http_redirects_to_https(self):
        path = reverse("account_login")
        response = self.client.get(path, HTTP_HOST="entrelineas.negui.es", HTTP_X_FORWARDED_PROTO="https")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.cookies["csrftoken"]["secure"])
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertNotContains(response, reverse("account_signup"))
        response = self.client.get(path, HTTP_HOST="entrelineas.negui.es")
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response.headers["Location"], "https://entrelineas.negui.es" + path)

    def test_login_csrf_accepts_public_origin_and_refuses_foreign_origin(self):
        client = Client(enforce_csrf_checks=True)
        headers = {"HTTP_HOST": "entrelineas.negui.es", "HTTP_X_FORWARDED_PROTO": "https"}
        client.get(reverse("account_login"), **headers)
        token = client.cookies["csrftoken"].value
        form = {"csrfmiddlewaretoken": token, "login": "nobody@example.com", "password": "wrong-password"}
        response = client.post(reverse("account_login"), form, HTTP_ORIGIN="https://entrelineas.negui.es", **headers)
        self.assertEqual(response.status_code, 200)  # Invalid credentials, valid CSRF.
        response = client.post(reverse("account_login"), form, HTTP_ORIGIN="https://foreign.example", **headers)
        self.assertEqual(response.status_code, 403)

    def test_login_cookie_and_private_content_keep_their_protection(self):
        user = self.make_user()
        response = self.client.post(reverse("account_login"), {"login": user.email, "password": "Lecturas-divertidas-826!"},
                                    HTTP_HOST="entrelineas.negui.es", HTTP_X_FORWARDED_PROTO="https")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.cookies["sessionid"]["secure"])
        self.assertTrue(response.cookies["sessionid"]["httponly"])
        self.assertEqual(self.client.get(reverse("reviews"), HTTP_HOST="entrelineas.negui.es", HTTP_X_FORWARDED_PROTO="https").status_code, 200)
        self.assertEqual(self.client.get(reverse("reviews"), HTTP_HOST="foreign.example", HTTP_X_FORWARDED_PROTO="https").status_code, 400)

    def test_registration_stays_closed_and_errors_are_not_debug_pages(self):
        headers = {"HTTP_HOST": "entrelineas.negui.es", "HTTP_X_FORWARDED_PROTO": "https"}
        self.assertTemplateUsed(self.client.get(reverse("account_signup"), **headers), "account/signup_closed.html")
        response = self.client.get("/this-page-does-not-exist/", **headers)
        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, "Traceback", status_code=404)
