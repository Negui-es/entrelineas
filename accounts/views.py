from django.utils.translation import gettext_lazy as _
from allauth.account.decorators import verified_email_required
from django.contrib import messages
from django.shortcuts import redirect, render
from .forms import ProfileForm


@verified_email_required
def profile(request):
    form = ProfileForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Perfil actualizado."))
        return redirect("profile")
    return render(request, "accounts/profile.html", {"form": form, "section": "profile"})
