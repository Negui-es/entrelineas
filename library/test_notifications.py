from django.urls import reverse
from django.utils import translation
from .tests import AppTestCase


class NotificationTests(AppTestCase):
    def test_login_uses_short_confirmation_once(self):
        user = self.make_user()
        response = self.client.post(reverse("account_login"), {
            "login": user.email, "password": "Lecturas-divertidas-826!",
        }, follow=True)
        self.assertContains(response, "Sesión iniciada.")
        self.assertContains(response, 'data-toast data-level="25"')
        self.assertContains(response, 'aria-label="Cerrar aviso"')
        self.assertNotContains(response, "Ha iniciado sesión exitosamente")
        response = self.client.get(reverse("reviews"))
        self.assertNotContains(response, "Sesión iniciada.")

    def test_auth_notifications_follow_selected_language(self):
        user = self.make_user()
        with translation.override("en"):
            response = self.client.post(reverse("account_login"), {
                "login": user.email, "password": "Lecturas-divertidas-826!",
            }, follow=True)
            self.assertContains(response, "Signed in.")
            self.assertContains(response, 'aria-label="Dismiss notification"')
        translation.activate("es")
