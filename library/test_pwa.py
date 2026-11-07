import json
from pathlib import Path
from PIL import Image
from django.conf import settings
from django.db.utils import OperationalError
from django.test import override_settings
from django.urls import reverse
from django.utils import translation
from unittest.mock import patch
from .tests import AppTestCase


@override_settings(SECURE_SSL_REDIRECT=False)
class InstallableAppTests(AppTestCase):
    def setUp(self):
        super().setUp()
        translation.activate("es")
        self.addCleanup(translation.activate, "es")

    def test_manifest_is_public_localised_and_has_one_identity(self):
        for language in ("es", "en", "de", "fr", "it"):
            with self.subTest(language=language), self.assertNumQueries(0):
                response = self.client.get(reverse("pwa_manifest"), {"lang": language, "next": "/private/123/"})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response["Content-Type"].startswith("application/manifest+json"))
            data = response.json()
            self.assertEqual(data["id"], "/")
            self.assertEqual(data["scope"], "/")
            self.assertEqual(data["start_url"], f"/{language}/")
            self.assertEqual(data["lang"], language)
            self.assertEqual(response["Content-Language"], language)
            self.assertEqual(data["display"], "standalone")
            self.assertNotIn("private", data["start_url"])
            self.assertFalse(data["prefer_related_applications"])
            self.assertEqual({icon["sizes"] for icon in data["icons"]}, {"192x192", "512x512"})
            self.assertTrue(any(icon["purpose"] == "maskable" for icon in data["icons"]))

    def test_native_icons_are_opaque_and_maskable_symbol_fits_safe_area(self):
        root = Path(settings.BASE_DIR) / "static/pwa"
        for name, size in [("icon-192.png", 192), ("icon-512.png", 512),
                           ("icon-maskable-512.png", 512), ("apple-touch-icon.png", 180)]:
            with Image.open(root / name) as image:
                self.assertEqual(image.size, (size, size))
                self.assertEqual(image.mode, "RGB")
        with Image.open(root / "icon-maskable-512.png") as image:
            # White logo pixels remain within the central 80%-diameter safe circle.
            for y in range(512):
                for x in range(512):
                    if min(image.getpixel((x, y))) > 230:
                        self.assertLessEqual((x-256)**2 + (y-256)**2, (512*.4)**2)

    def test_login_contains_install_metadata_without_footer_install_action_or_open_registration(self):
        response = self.client.get(reverse("account_login"))
        self.assertContains(response, 'rel="manifest"')
        self.assertContains(response, 'rel="apple-touch-icon"')
        self.assertContains(response, 'name="apple-mobile-web-app-capable" content="yes"')
        self.assertNotContains(response, 'data-install-open')
        self.assertContains(response, 'id="install-dialog"')
        self.assertNotContains(response, reverse("account_signup"))
        self.assertIn("worker-src 'self'", response["Content-Security-Policy"])

    def test_worker_has_root_scope_and_deterministic_public_only_config(self):
        with self.assertNumQueries(0):
            first = self.client.get(reverse("pwa_worker"))
            second = self.client.get(reverse("pwa_worker"), HTTP_ACCEPT_LANGUAGE="de")
        self.assertEqual(first.content, second.content)
        self.assertEqual(first["Service-Worker-Allowed"], "/")
        self.assertTrue(first["Content-Type"].startswith("text/javascript"))
        text = first.content.decode()
        self.assertNotIn("__PWA_CONFIG__", text)
        config = json.loads(text.split("const CONFIG = ")[1].split(";", 1)[0])
        self.assertEqual(set(config["offline"]), {"es", "en", "de", "fr", "it"})
        self.assertTrue(all(url.startswith("/static/pwa/") for url in config["assets"]))
        self.assertIn('credentials: "omit"', text)

    def test_offline_shell_needs_no_database_or_account(self):
        with patch("django.db.backends.utils.CursorWrapper.execute", side_effect=OperationalError("Database unavailable")):
            response = self.client.get(reverse("pwa_offline", args=["es"]))
        self.assertContains(response, "La conexión ha perdido el marcapáginas")
        self.assertNotContains(response, 'name="csrfmiddlewaretoken"')
        self.assertNotContains(response, 'name="password"')
        self.assertContains(self.client.get(reverse("pwa_offline", args=["en"])), "The connection has lost its bookmark")
        self.assertEqual(self.client.get(reverse("pwa_offline", args=["unknown"])).status_code, 404)

    def test_account_has_install_option_and_operations_are_get_only(self):
        self.client.force_login(self.make_user())
        self.assertContains(self.client.get(reverse("profile")), "Instalar Entrelíneas")
        for name in ("pwa_manifest", "pwa_worker"):
            self.assertEqual(self.client.post(reverse(name)).status_code, 405)
