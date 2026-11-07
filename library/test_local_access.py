from django.test import Client, override_settings
from django.urls import reverse
from .tests import AppTestCase


@override_settings(DEBUG=False, SECURE_SSL_REDIRECT=True, SESSION_COOKIE_SECURE=True, CSRF_COOKIE_SECURE=True,
                   ALLOWED_HOSTS=["127.0.0.1", "localhost", "entrelineas.negui.es"],
                   SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"))
class LocalAccessTests(AppTestCase):
    def test_direct_local_http_can_log_in_with_real_csrf_validation(self):
        user = self.make_user()
        client = Client(enforce_csrf_checks=True)
        headers = {"HTTP_HOST": "127.0.0.1:18743", "REMOTE_ADDR": "127.0.0.1"}
        response = client.get(reverse("account_login"), **headers)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.cookies["csrftoken"]["secure"])
        response = client.post(reverse("account_login"), {
            "login": user.email, "password": "Lecturas-divertidas-826!",
            "csrfmiddlewaretoken": client.cookies["csrftoken"].value,
        }, HTTP_ORIGIN="http://127.0.0.1:18743", **headers)
        self.assertEqual(response.status_code, 302)
        self.assertFalse(response.cookies["sessionid"]["secure"])
        self.assertTrue(response.cookies["sessionid"]["httponly"])
        self.assertEqual(client.get(reverse("reviews"), **headers).status_code, 200)

    def test_public_http_still_redirects_and_https_cookies_remain_secure(self):
        response = self.client.get(reverse("account_login"), HTTP_HOST="entrelineas.negui.es")
        self.assertEqual(response.status_code, 301)
        response = self.client.get(reverse("account_login"), HTTP_HOST="entrelineas.negui.es", HTTP_X_FORWARDED_PROTO="https")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.cookies["csrftoken"]["secure"])

    def test_proxy_and_non_loopback_peers_cannot_get_local_exception(self):
        for headers in [
            {"REMOTE_ADDR": "192.0.2.1"},
            {"REMOTE_ADDR": "127.0.0.1", "HTTP_CF_RAY": "example"},
            {"REMOTE_ADDR": "127.0.0.1", "HTTP_X_FORWARDED_FOR": "192.0.2.1"},
        ]:
            response = self.client.get(reverse("account_login"), HTTP_HOST="127.0.0.1:18743", **headers)
            self.assertEqual(response.status_code, 301)
