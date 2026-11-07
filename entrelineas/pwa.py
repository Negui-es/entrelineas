"""Public install metadata and offline shell. Never renders user context."""
import hashlib
import json
from pathlib import Path
from django.conf import settings
from django.http import Http404, HttpResponse, JsonResponse
from django.template.loader import render_to_string
from django.templatetags.static import static
from django.urls import reverse
from django.utils import translation
from django.utils.translation import gettext as _
from django.views.decorators.http import require_safe

ICONS = [("icon-192.png", 192, "any"), ("icon-512.png", 512, "any"), ("icon-maskable-512.png", 512, "maskable")]


@require_safe
def manifest(request):
    language = request.GET.get("lang", translation.get_language())
    if language not in dict(settings.LANGUAGES):
        language = settings.LANGUAGE_CODE
    with translation.override(language):
        data = {"id": "/", "name": "Entrelíneas", "short_name": "Entrelíneas", "lang": language,
                "description": _("Tu biblioteca y tus reseñas, siempre a mano."),
                "start_url": reverse("home"), "scope": "/", "display": "standalone",
                "background_color": "#f6f5fb", "theme_color": "#6845a5",
                "prefer_related_applications": False, "categories": ["books", "lifestyle"],
                "icons": [{"src": static("pwa/" + name), "sizes": f"{size}x{size}", "type": "image/png", "purpose": purpose} for name, size, purpose in ICONS]}
    response = JsonResponse(data, content_type="application/manifest+json", json_dumps_params={"ensure_ascii": False})
    response["Content-Language"] = language
    return response


def offline_html(language):
    with translation.override(language):
        return render_to_string("pwa/offline.html", {"language": language, "home_url": f"/{language}/"})


@require_safe
def offline(request, language):
    if language not in dict(settings.LANGUAGES):
        raise Http404
    response = HttpResponse(offline_html(language))
    response["Content-Language"] = language
    return response


@require_safe
def service_worker(request):
    languages = [code for code, label in settings.LANGUAGES]
    shells = {code: reverse("pwa_offline", args=[code]) for code in languages}
    assets = [static("pwa/offline.css"), static("pwa/icon-192.png"), static("pwa/apple-touch-icon.png")]
    # Changing public assets or translations creates a new worker/cache version.
    revision = json.dumps([assets, [offline_html(code) for code in languages]], ensure_ascii=True)
    config = {"version": hashlib.sha256(revision.encode()).hexdigest()[:16], "assets": assets, "offline": shells, "defaultLanguage": settings.LANGUAGE_CODE}
    source = (Path(settings.BASE_DIR) / "static/pwa/worker.js").read_text(encoding="utf-8")
    response = HttpResponse(source.replace("__PWA_CONFIG__", json.dumps(config)), content_type="text/javascript; charset=utf-8")
    response["Service-Worker-Allowed"] = "/"
    response["Cache-Control"] = "no-cache"
    return response
