from django.conf import settings
from django.http import HttpResponseRedirect
from django.urls import Resolver404, resolve, reverse, translate_url
from django.utils import translation
from django.utils.cache import patch_vary_headers
from django.utils.deprecation import MiddlewareMixin
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


class LegacyURLMiddleware(MiddlewareMixin):
    """Keep old bookmarks and signed email links, without duplicating page URLs."""
    def process_request(self, request):
        if translation.get_language_from_path(request.path_info) or request.path_info.startswith(("/static/", "/admin/", "/salud/")):
            return None
        try:
            match = resolve(request.path_info, urlconf="entrelineas.legacy_urls")
            target = reverse(match.view_name, args=match.args, kwargs=match.kwargs)
        except (Resolver404, ValueError):
            return None
        query = request.META.get("QUERY_STRING", "")
        if query:
            target += "?" + query
        response = HttpResponseRedirect(target, preserve_request=request.method not in {"GET", "HEAD"})
        response["Cache-Control"] = "private, no-store"
        patch_vary_headers(response, ("Accept-Language", "Cookie"))
        return response


def language_navigation(request):
    current = translation.get_language() or "es"
    links = []
    for code, label in settings.LANGUAGES:
        url = translate_url(request.get_full_path(), code)
        if url == request.get_full_path() and code != current:
            with translation.override(code):
                url = reverse("home")
        parts = urlsplit(url)
        query = []
        for key, value in parse_qsl(parts.query, keep_blank_values=True):
            if key == "next" and value.startswith("/") and not value.startswith("//"):
                original_language = translation.get_language_from_path(value) or current
                with translation.override(original_language):
                    value = translate_url(value, code)
            query.append((key, value))
        url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
        links.append({"code": code, "label": label, "url": url})
    return {"current_language": current, "language_links": links}
