from django.utils.translation import gettext_lazy as _
from allauth.account.decorators import verified_email_required
from django.contrib import messages
from django.core import signing
from django.core.cache import cache
import secrets
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from accounts.models import User
from entrelineas.errors import pick_message
from . import catalog
from .catalog_store import store_edition
from .models import Book, Wishlist, WishItem, Edition
from .work_identity import align_review
from . import local_catalog

SALT = "entrelineas-catalog-v2"


def source_label(provider):
    return "Entrelíneas" if provider == "local" else catalog.PROVIDERS.get(provider, provider)


def _sign(request, data, target=None):
    if data.get("kind") == "work_group":
        reference = secrets.token_urlsafe(24)
        cache.set(f"catalog:group:{request.user.pk}:{reference}", data, timeout=3600)
        data = {"kind": "work_group", "group_ref": reference}
    return signing.dumps({"user": request.user.pk, "data": data, "target": target}, salt=SALT, compress=True)


def _load(request, token):
    try:
        if len(token) > 60000:
            return None
        value = signing.loads(token, salt=SALT, max_age=3600)
        if value["user"] != request.user.pk or not isinstance(value["data"], dict):
            return None
        if value["data"].get("kind") == "work_group":
            reference = value["data"].get("group_ref", "")
            if not isinstance(reference, str) or len(reference) != 32:
                return None
            data = cache.get(f"catalog:group:{request.user.pk}:{reference}")
            if not isinstance(data, dict) or data.get("kind") != "work_group":
                return None
            value["data"] = data
        return value
    except (signing.BadSignature, KeyError, TypeError, ValueError):
        return None


def _target(request, pk):
    if not pk:
        return None
    try:
        return get_object_or_404(Book, pk=int(pk), owner=request.user)
    except (ValueError, TypeError):
        raise Http404(_("Libro no encontrado"))


@verified_email_required
def search(request):
    query, mode, provider = request.GET.get("q", "").strip(), request.GET.get("mode", "all"), request.GET.get("source", "all")
    target = _target(request, request.GET.get("link"))
    try:
        page = max(1, min(50, int(request.GET.get("page", 1))))
    except (ValueError, TypeError):
        page = 1
    results, error = None, ""
    if query:
        try:
            results = catalog.search(query, mode, page, provider)
            if provider == "all":
                results = local_catalog.supplement(results, query, mode, page)
            for item in results["items"]:
                members = item.get("editions", [item])
                providers = {p["provider"] for member in members for p in [member, *member.get("alternatives", [])]}
                item["sources_label"] = " · ".join(source_label(p) for p in sorted(providers))
                item["selection"] = _sign(request, item, target.pk if target else None)
        except catalog.CatalogError as exc:
            error = str(exc)
    unavailable = bool(results and results.get("unavailable"))
    if results and not unavailable:
        if results.get("failed_providers"):
            messages.info(request, _("Algunas estanterías están tardando en abrir. Te mostramos lo que hemos encontrado; puedes volver a buscar más tarde."))
        for warning in results.get("warnings", []):
            messages.info(request, warning)
    return render(request, "library/catalog_search.html", {"section": "catalog", "catalog_query": query, "mode": mode, "source": provider, "results": results, "error": error, "page": page, "previous_page": page-1, "next_page": page+1, "target": target, "catalog_providers": catalog.enabled_providers(), "catalog_problem": pick_message("catalog") if unavailable else None}, status=503 if unavailable else 200)


@verified_email_required
def preview(request):
    payload = _load(request, request.GET.get("selection", ""))
    if not payload:
        messages.info(request, _("El resultado ha caducado. Vuelve a buscar el libro."))
        return redirect("catalog_search")
    target, selection = _target(request, payload.get("target")), payload["data"]
    try:
        if selection.get("kind") == "work_group":
            options = selection["editions"]
            for option in options:
                option["selection"] = _sign(request, option, target.pk if target else None)
                providers = {p["provider"] for p in [option, *option.get("alternatives", [])]}
                option["sources_label"] = " · ".join(source_label(p) for p in sorted(providers))
            return render(request, "library/catalog_options.html", {"section": "catalog", "item": selection, "options": options, "target": target})
        if (selection.get("provider") == "inventaire" and selection.get("kind") in {"work", "author"}) or (selection.get("provider") == "bookbrainz" and selection.get("kind") == "author"):
            if selection["provider"] == "bookbrainz":
                from .catalog_extra import bookbrainz_options
                options = bookbrainz_options(selection)
            else:
                options = catalog.inventaire_options(selection)
            for option in options:
                option["selection"] = _sign(request, option, target.pk if target else None)
                option["sources_label"] = catalog.PROVIDERS[option["provider"]]
            selection["sources_label"] = catalog.PROVIDERS[selection["provider"]]
            return render(request, "library/catalog_options.html", {"section": "catalog", "item": selection, "options": options, "target": target})
        local = None
        if selection.get("provider") == "local":
            local = get_object_or_404(Edition, pk=selection["source_id"])
        elif catalog.canonical_isbn(selection.get("isbn", "")):
            local = Edition.objects.filter(isbn=catalog.canonical_isbn(selection["isbn"])).first()
        item = local_catalog.edition_data(local) if local else catalog.details(selection)
    except catalog.CatalogError as exc:
        messages.error(request, str(exc))
        return redirect("catalog_search")
    item["color"] = "blue"
    for source in item["sources"]:
        source["label"] = catalog.PROVIDERS[source["provider"]]
    work_selection = {"provider": "inventaire", "kind": "work", "source_id": item["work_key"], "title": item["title"], "author": item["author"]} if item["provider"] == "inventaire" else None
    return render(request, "library/catalog_preview.html", {"section": "catalog", "item": item, "selection": _sign(request, item, target.pk if target else None), "other_editions": _sign(request, work_selection, target.pk if target else None) if work_selection else None, "target": target})


@verified_email_required
@require_POST
def save(request):
    payload = _load(request, request.POST.get("selection", ""))
    if not payload or not {"sources", "work_key", "field_sources", "total_pages", "publisher"}.issubset(payload["data"]):
        raise Http404(_("Abre primero la ficha de la edición"))
    data, target = payload["data"], _target(request, payload.get("target"))
    destination = request.POST.get("destination")
    if destination not in {"library", "review", "wishes", "link", "cover"} or (destination == "link" and not target):
        raise Http404(_("Destino no válido"))
    if target and data.get("total_pages") and target.current_page > data["total_pages"]:
        messages.error(request, _("La edición tiene menos páginas que tu progreso actual. Revisa primero tu página de lectura; tus datos no han cambiado."))
        return redirect(target)
    try:
        with transaction.atomic():
            User.objects.select_for_update().get(pk=request.user.pk)
            edition = store_edition(data)
            if destination == "wishes":
                listing, unused = Wishlist.objects.get_or_create(owner=request.user)
                unused, created = WishItem.objects.get_or_create(wishlist=listing, catalog_edition=edition, defaults={"title": edition.title, "author": edition.author, "color": "blue", "edition": " · ".join(filter(None, [edition.publisher, edition.publication_date]))[:160]})
                messages.success(request, _("Añadido a deseos.") if created else _("Esta edición ya está en tus deseos."))
                return redirect("wishlist")
            defaults = {"title": edition.title, "author": edition.author, "isbn": edition.isbn or "", "total_pages": edition.total_pages, "color": "blue"}
            if target:
                book = target
                for field, value in defaults.items():
                    setattr(book, field, value)
                book.catalog_edition = edition
                book.save()
                align_review(book)
                messages.success(request, _("Edición actualizada."))
            else:
                book, created = Book.objects.get_or_create(owner=request.user, catalog_edition=edition, defaults=defaults)
                messages.success(request, _("Libro añadido.") if created else _("Esta edición ya está en tu biblioteca."))
    except catalog.CatalogError as exc:
        messages.error(request, str(exc))
        return redirect("catalog_search")
    if destination == "cover":
        return redirect("book_cover", pk=book.pk)
    return redirect(reverse("review_create") + f"?book={book.pk}") if destination == "review" else redirect(book)
