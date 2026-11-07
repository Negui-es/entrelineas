import secrets

from allauth.account.decorators import verified_email_required
from django import forms
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.shortcuts import render
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_http_methods

from .goodreads import parse_export, preview_rows, import_rows
from .goodreads_catalog import prepare_rows, match_remote
from .catalog import CatalogError, enabled_providers
from . import native_csv
from .models import Book, Review, WishItem

PREVIEW_PREFIX = "goodreads:v3"


class GoodreadsForm(forms.Form):
    source = forms.ChoiceField(label=_("Origen del archivo"), choices=[("goodreads", "Goodreads"), ("entrelineas", "Entrelíneas")], widget=forms.RadioSelect)
    file = forms.FileField(label=_("Archivo CSV"), widget=forms.ClearableFileInput(attrs={"accept": ".csv,text/csv", "class": "wizard-file-input", "aria-describedby": "wizard-file-help"}))


@verified_email_required
@require_http_methods(["GET"])
def library_export(request):
    response = HttpResponse(native_csv.export_csv(request.user), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="entrelineas-{timezone.localdate().isoformat()}.csv"'
    response["X-Content-Type-Options"] = "nosniff"
    return response


@verified_email_required
@require_http_methods(["GET", "POST"])
def goodreads_import(request):
    form = GoodreadsForm(initial={"source": request.GET.get("source")})
    context = {"section": "library", "form": form,
               "catalog_providers": " · ".join(enabled_providers().values())}
    if request.method == "POST" and request.POST.get("action") == "match":
        token = request.POST.get("token", "")
        key = f"{PREVIEW_PREFIX}:{request.user.pk}:{token}"
        if len(token) != 43:
            return JsonResponse({"error": "expired"}, status=404)
        if not cache.add(key + ":lock", True, 180):
            return JsonResponse({"error": "busy"}, status=409)
        try:
            rows = cache.get(key)
            if rows and rows[0].get("import_source") == "entrelineas":
                return JsonResponse({"error": "unsupported"}, status=400)
            try:
                index = int(request.POST.get("index", ""))
            except ValueError:
                index = -1
            if rows is None or not 0 <= index < len(rows):
                return JsonResponse({"error": "expired"}, status=404)
            row = rows[index]
            try:
                match_remote(row)
            except CatalogError:
                # Preserve any local match and let the CSV import continue.
                row["match_label"] = _("No se ha podido completar la búsqueda externa")
            cache.set(key, rows, 1800)
            return JsonResponse({"external_id": row["external_id"],
                **{field: row.get(field, "") for field in ("match_label", "match_title", "match_author", "match_isbn", "match_cover", "match_cover_from_work")}})
        finally:
            cache.delete(key + ":lock")
    if request.method == "POST" and request.POST.get("action") == "confirm":
        token = request.POST.get("token", "")
        key = f"{PREVIEW_PREFIX}:{request.user.pk}:{token}"
        payload = cache.get(key) if len(token) == 43 else None
        if payload is None:
            context["error"] = _("La vista previa ha caducado o ya se ha importado. Vuelve a subir el CSV.")
        else:
            if not cache.add(key + ":lock", True, 180):
                context["error"] = _("La búsqueda sigue en curso. Vuelve a subir el CSV si la página no responde.")
            else:
                try:
                    source = payload[0].get("import_source", "goodreads")
                    context["result"] = (native_csv.import_rows if source == "entrelineas" else import_rows)(request.user, payload)
                    context["source"] = source
                    cache.delete(key)
                finally:
                    cache.delete(key + ":lock")
    elif request.method == "POST":
        # Old bookmarks/forms remain compatible with the previous Goodreads flow.
        posted = request.POST.copy()
        posted.setdefault("source", "goodreads")
        form = GoodreadsForm(posted, request.FILES)
        context["form"] = form
        if form.is_valid():
            try:
                source = form.cleaned_data["source"]
                rows, issues = (native_csv.parse_csv if source == "entrelineas" else parse_export)(form.cleaned_data["file"])
            except ValidationError as exc:
                form.add_error("file", exc)
            else:
                if source == "goodreads":
                    prepare_rows(rows)
                token = secrets.token_urlsafe(32)
                if source == "entrelineas":
                    for row in rows:
                        row["import_source"] = source
                cache.set(f"{PREVIEW_PREFIX}:{request.user.pk}:{token}", rows, 1800)
                preview = (native_csv.preview_rows if source == "entrelineas" else preview_rows)(request.user, rows)
                context.update(token=token, source=source, native=source == "entrelineas",
                               match_ids=[r["external_id"] for r in rows],
                               match_titles=[r["title"] for r in rows],
                               import_preview=preview,
                               library_preview=[r for r in preview if r["destination"] == "library"][:50],
                               wish_preview=[r for r in preview if r["destination"] == "wishlist"][:50],
                               library_count=sum(r["destination"] == "library" for r in rows),
                               wish_count=sum(r["destination"] == "wishlist" for r in rows),
                               total=len(rows), review_count=sum(bool(r["text"] or r["rating"]) for r in rows),
                               issues=issues[:20], issue_count=len(issues))
    if request.method == "POST" or request.resolver_match.url_name != "library_transfer" or request.GET.get("direction") == "import" or request.GET.get("source"):
        context["transfer_stage"] = "file" if form["source"].value() in ("goodreads", "entrelineas") else "source"
    else:
        context["transfer_stage"] = "export" if request.GET.get("direction") == "export" else "direction"
    if not context.get("token") and not context.get("result"):
        context["export_summary"] = {
            "books": Book.objects.filter(owner=request.user).count(),
            "reviews": Review.objects.filter(book__owner=request.user).count(),
            "wishes": WishItem.objects.filter(wishlist__owner=request.user).count(),
        }
    return render(request, "library/goodreads_import.html", context)
