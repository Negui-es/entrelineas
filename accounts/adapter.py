from allauth.account.adapter import DefaultAccountAdapter
from django.conf import settings


class AccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request):
        return settings.REGISTRATION_OPEN

    def clean_email(self, email):
        return super().clean_email(email).lower().strip()
