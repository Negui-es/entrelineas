from django.utils.translation import gettext_lazy as _
from allauth.account.forms import SignupForm as AllauthSignupForm
from allauth.account.forms import LoginForm as AllauthLoginForm
from django import forms
from .models import User


class LoginForm(AllauthLoginForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["password"].help_text = ""
        for name in ("login", "password"):
            self.fields[name].widget.attrs.pop("placeholder", None)


class SignupForm(AllauthSignupForm):
    display_name = forms.CharField(label=_("Nombre"), max_length=60,
                                  widget=forms.TextInput(attrs={"autocomplete": "nickname"}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.order_fields(["display_name", "email", "password1", "password2"])

    def save(self, request):
        user = super().save(request)
        user.display_name = self.cleaned_data["display_name"]
        user.save(update_fields=["display_name"])
        return user


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["display_name", "theme"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["theme"].required = False
        self.fields["theme"].widget = forms.RadioSelect(choices=User.Theme.choices)
        self.fields["theme"].widget.attrs["data-theme-select"] = ""
        self.fields["theme"].widget.attrs["aria-describedby"] = "theme-help"

    def clean_theme(self):
        return self.cleaned_data.get("theme") or self.instance.theme or User.Theme.AUTO
