from django.contrib import admin
from django.urls import include, path
from django.conf.urls.i18n import i18n_patterns
from django.utils.translation import gettext_lazy as _
from django.views.i18n import JavaScriptCatalog
from library.views import health
from . import pwa

handler404 = "entrelineas.errors.page_not_found"
handler500 = "entrelineas.errors.server_error"

urlpatterns = [
    path("manifest.webmanifest", pwa.manifest, name="pwa_manifest"),
    path("service-worker.js", pwa.service_worker, name="pwa_worker"),
    path("pwa/offline/<str:language>/", pwa.offline, name="pwa_offline"),
    path("admin/", admin.site.urls),
    path("salud/", health),
]
urlpatterns += i18n_patterns(
    path(_("cuenta/"), include("accounts.urls")),
    path(_("acceso/"), include("accounts.auth_urls")),
    path("translations.js", JavaScriptCatalog.as_view(), name="javascript-catalog"),
    path("", include("library.urls")),
)
admin.site.site_header = _("Entrelíneas · Administración")
admin.site.site_title = "Entrelíneas"
