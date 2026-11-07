from django.urls import include, path

urlpatterns = [
    path("cuenta/", include("accounts.urls")),
    path("acceso/", include("allauth.account.urls")),
    path("", include("entrelineas.legacy_library_urls")),
]
