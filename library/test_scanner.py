from django.urls import reverse
from django.utils import translation
from .tests import AppTestCase


class ScannerInterfaceTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.make_user())

    def test_search_and_manual_entry_share_one_accessible_modal(self):
        for name in ("catalog_search", "book_create"):
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertContains(response, '<dialog id="scanner-dialog"', count=1)
                self.assertContains(response, 'aria-labelledby="scanner-title"')
                self.assertContains(response, 'aria-describedby="scanner-instructions"')
                self.assertNotContains(response, 'id="scan-start"')
                self.assertNotContains(response, 'id="scanner-panel"')

    def test_modal_controls_follow_the_selected_language(self):
        for code, label in [("es", "Cerrar escáner"), ("en", "Close scanner"), ("de", "Scanner schließen"),
                            ("fr", "Fermer le scanner"), ("it", "Chiudi scanner")]:
            with self.subTest(language=code), translation.override(code):
                self.assertContains(self.client.get(reverse("catalog_search")), f'aria-label="{label}"')
