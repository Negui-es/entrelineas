"""Localized paths; the underlying allauth views and token formats stay intact."""
from django.urls import path, register_converter
from django.utils.translation import gettext_lazy as _
from allauth.account import views


class Base36Converter:
    regex = "[0-9A-Za-z]+"

    def to_python(self, value):
        return value

    def to_url(self, value):
        return str(value)


register_converter(Base36Converter, "uid")

urlpatterns = [
    path(_("iniciar-sesion/"), views.login, name="account_login"),
    path(_("cerrar-sesion/"), views.logout, name="account_logout"),
    path(_("inactiva/"), views.account_inactive, name="account_inactive"),
    path(_("registro/"), views.signup, name="account_signup"),
    path(_("verificar-acceso/"), views.reauthenticate, name="account_reauthenticate"),
    path(_("email/"), views.email, name="account_email"),
    path(_("confirmar-email/"), views.email_verification_sent, name="account_email_verification_sent"),
    path(_("confirmar-email/<str:key>/"), views.confirm_email, name="account_confirm_email"),
    path(_("contrasena/cambiar/"), views.password_change, name="account_change_password"),
    path(_("contrasena/crear/"), views.password_set, name="account_set_password"),
    path(_("contrasena/recuperar/"), views.password_reset, name="account_reset_password"),
    path(_("contrasena/recuperar/enviada/"), views.password_reset_done, name="account_reset_password_done"),
    path(_("contrasena/nueva/completada/"), views.password_reset_from_key_done, name="account_reset_password_from_key_done"),
    path(_("contrasena/nueva/<uid:uidb36>-<str:key>/"), views.password_reset_from_key, name="account_reset_password_from_key"),
    path(_("codigo/confirmar/"), views.confirm_login_code, name="account_confirm_login_code"),
]
