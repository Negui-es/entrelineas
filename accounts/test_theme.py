from django.urls import reverse
from django.utils import translation

from library.tests import AppTestCase


class ThemeTests(AppTestCase):
    def setUp(self):
        super().setUp()
        translation.activate("es")
        self.addCleanup(translation.deactivate)
        self.user = self.make_user()
        self.client.force_login(self.user)

    def test_default_uses_system_theme(self):
        self.assertEqual(self.user.theme, "auto")
        response = self.client.get(reverse("profile"))
        self.assertContains(response, 'data-theme="auto"')
        self.assertEqual(response.context["form"]["theme"].value(), "auto")
        self.assertContains(response, 'value="auto"')

    def test_saved_theme_applies_across_pages(self):
        for theme in ("light", "dark", "auto"):
            response = self.client.post(reverse("profile"), {"display_name": "Lector", "theme": theme})
            self.assertRedirects(response, reverse("profile"))
            self.user.refresh_from_db()
            self.assertEqual(self.user.theme, theme)
            self.assertContains(self.client.get(reverse("home")), f'data-theme="{theme}"')

    def test_invalid_theme_is_rejected_and_old_forms_keep_preference(self):
        self.user.theme = "dark"
        self.user.save(update_fields=["theme"])
        response = self.client.post(reverse("profile"), {"display_name": "Lector", "theme": "invalid"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("theme", response.context["form"].errors)
        self.client.post(reverse("profile"), {"display_name": "Otro nombre"})
        self.user.refresh_from_db()
        self.assertEqual(self.user.theme, "dark")

    def test_profile_only_updates_current_user(self):
        other = self.make_user("otra@example.com")
        self.client.post(reverse("profile"), {"display_name": "Lector", "theme": "dark", "id": other.pk})
        other.refresh_from_db()
        self.assertEqual(other.theme, "auto")
