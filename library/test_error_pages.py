from django.urls import reverse
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.db import OperationalError
from django.test import RequestFactory, override_settings
from django.urls import path

from entrelineas import errors
from . import catalog
from .tests import AppTestCase


def failing_view(request):
    raise OperationalError("PRIVATE database connection details must never be displayed")


urlpatterns = [path("failure/", failing_view)]
handler404 = errors.page_not_found
handler500 = errors.server_error


@override_settings(DEBUG=False, SECURE_SSL_REDIRECT=False)
class ErrorPageTests(AppTestCase):
    def test_real_404_does_not_disclose_path_query_or_exception(self):
        response = self.client.get("/missing-private-title/?token=do-not-display")
        self.assertContains(response, "404 · Página no encontrada", status_code=404)
        self.assertNotContains(response, "missing-private-title", status_code=404)
        self.assertNotContains(response, "do-not-display", status_code=404)
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")

    def test_every_message_renders_without_database_access(self):
        request = RequestFactory().get("/failure/")
        for code in (404, 500):
            for message in errors.MESSAGES[code]:
                with self.subTest(code=code, message=message), patch.object(errors, "choice", return_value=message), self.assertNumQueries(0):
                    response = errors.error_response(request, code)
                    self.assertContains(response, message[0], status_code=code)
                    self.assertNotContains(response, "csrfmiddlewaretoken", status_code=code)

    def test_random_selection_runs_for_each_response_and_keeps_status(self):
        request = RequestFactory().get("/missing/")
        with patch.object(errors, "choice", side_effect=[errors.MESSAGES[404][0], errors.MESSAGES[404][1]]) as choose:
            first = errors.page_not_found(request, Exception("secret"))
            second = errors.page_not_found(request, Exception("secret"))
        self.assertEqual(choose.call_count, 2)
        self.assertNotEqual(first.content, second.content)
        self.assertEqual((first.status_code, second.status_code), (404, 404))

    @override_settings(ROOT_URLCONF=__name__)
    def test_database_exception_uses_custom_500_and_hides_details(self):
        self.client.raise_request_exception = False
        response = self.client.get("/failure/")
        self.assertContains(response, "500 · Algo ha fallado", status_code=500)
        self.assertNotContains(response, "PRIVATE", status_code=500)
        self.assertNotContains(response, "Traceback", status_code=500)
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")

    def test_500_post_does_not_offer_to_resubmit_a_write(self):
        request = RequestFactory().post("/save/")
        response = errors.server_error(request)
        self.assertNotContains(response, "Volver a intentarlo", status_code=500)
        self.assertContains(response, "comprueba el resultado", status_code=500)

    def test_standalone_outage_has_no_external_assets(self):
        from scripts.build_error_pages import standalone
        import json
        html = standalone({**errors.error_context(503), "offline": True,
                           "offline_messages": json.dumps(errors.MESSAGES[503], ensure_ascii=False)})
        self.assertIn("503 · Biblioteca en pausa", html)
        self.assertIn("<style>", html)
        self.assertIn("<script>", html)
        self.assertNotIn('src="/static/', html)
        self.assertNotIn('href="/static/', html)
        self.assertNotIn("setInterval", html)
        self.assertTrue((Path(settings.BASE_DIR) / "deploy/offline.html").exists())

    def test_catalogue_failure_is_not_an_empty_search(self):
        self.client.force_login(self.make_user())
        with patch.object(catalog, "_worker", side_effect=catalog.CatalogError("unavailable")):
            response = self.client.get(reverse("catalog_search"), {"q": "La sombra del viento", "mode": "title"})
        self.assertContains(response, "Una pausa en la búsqueda", status_code=503)
        self.assertContains(response, 'value="La sombra del viento"', status_code=503)
        self.assertNotContains(response, "No hemos encontrado ese libro", status_code=503)

    def test_partial_failure_keeps_results_and_empty_success_is_not_an_error(self):
        self.client.force_login(self.make_user())
        item = {"provider": "openlibrary", "kind": "edition", "source_id": "OL1M", "title": "Un libro", "author": "Autora", "isbn": ""}
        def partial(provider, *args):
            if provider == "openlibrary":
                return {"items": [item], "has_next": False}
            raise catalog.CatalogError("unavailable")
        with patch.object(catalog, "_worker", side_effect=partial):
            response = self.client.get(reverse("catalog_search"), {"q": "Un libro"})
        self.assertContains(response, "Un libro")
        self.assertNotContains(response, "Una pausa en la búsqueda")
        with patch.object(catalog, "_worker", return_value={"items": [], "has_next": False}):
            response = self.client.get(reverse("catalog_search"), {"q": "Un libro"})
        self.assertContains(response, "No hemos encontrado ese libro")
