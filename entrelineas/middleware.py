from urllib.parse import urlsplit, urlunsplit
from django.conf import settings
from django.middleware.security import SecurityMiddleware
from django.core.exceptions import DisallowedHost


def direct_loopback(request):
    """Only direct local HTTP; a request arriving through a proxy never qualifies."""
    if request.is_secure() or request.META.get("REMOTE_ADDR") not in {"127.0.0.1", "::1"}:
        return False
    if any(request.META.get(header) for header in (
        "HTTP_CF_RAY", "HTTP_CF_CONNECTING_IP", "HTTP_FORWARDED", "HTTP_X_FORWARDED_FOR", "HTTP_X_FORWARDED_PROTO",
    )):
        return False
    try:
        return urlsplit("//" + request.get_host()).hostname in {"127.0.0.1", "localhost", "::1"}
    except (DisallowedHost, ValueError):
        return False


class LocalAccessSecurityMiddleware(SecurityMiddleware):
    def process_request(self, request):
        if not direct_loopback(request):
            return super().process_request(request)

    def process_response(self, request, response):
        response = super().process_response(request, response)
        if direct_loopback(request):
            for name in (settings.SESSION_COOKIE_NAME, settings.CSRF_COOKIE_NAME):
                if name in response.cookies:
                    response.cookies[name]["secure"] = False
            location = response.get("Location")
            if location:
                parts = urlsplit(location)
                if parts.scheme == "https" and parts.netloc == request.get_host():
                    response["Location"] = urlunsplit(("http", parts.netloc, parts.path, parts.query, parts.fragment))
        return response


class PrivateResponseMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if not request.path.startswith("/static/"):
            response["Cache-Control"] = "private, no-store"
            response["X-Robots-Tag"] = "noindex, nofollow"
        response["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data: blob: https://covers.openlibrary.org https://archive.org https://*.us.archive.org https://*.eu.archive.org https://inventaire.io https://images.cdn.europe-west1.gcp.commercetools.com; media-src 'self' blob:; font-src 'self'; connect-src 'self'; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'; worker-src 'self'; manifest-src 'self'"
        )
        response["Permissions-Policy"] = "camera=(self), microphone=()"
        return response
