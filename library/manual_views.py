import uuid
from allauth.account.decorators import verified_email_required
from django.contrib import messages
from django.core import signing
from django.db import IntegrityError, transaction
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.utils import timezone
from accounts.models import User
from .catalog import canonical_isbn
from .manual_forms import ISBNForm, EditionMetadataForm, CoverForm
from .models import Book, Edition
from .work_identity import resolve_work, work_candidates

SALT = "entrelineas-user-edition-v1"


def add_reading(user, edition):
    book, unused = Book.objects.get_or_create(owner=user, catalog_edition=edition, defaults={
        "title": edition.title, "author": edition.author, "isbn": edition.isbn or "",
        "total_pages": edition.total_pages, "color": "blue"})
    return book


@verified_email_required
def create(request):
    context = {"section": "library", "stage": "isbn"}
    isbn_form = ISBNForm(request.POST if request.method == "POST" and request.POST.get("action") == "lookup" else None)
    context["isbn_form"] = isbn_form
    isbn = canonical_isbn(request.GET.get("isbn", ""))
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "lookup" and isbn_form.is_valid():
            return redirect(reverse("book_create") + "?isbn=" + isbn_form.cleaned_data["isbn"])
        if action in {"reuse", "details"}:
            isbn = canonical_isbn(request.POST.get("isbn", ""))
        if action == "create":
            try:
                payload = signing.loads(request.POST.get("selection", ""), salt=SALT, max_age=3600)
                if payload["user"] != request.user.pk or not canonical_isbn(payload["data"]["isbn"]):
                    raise ValueError
                data = payload["data"]
            except (signing.BadSignature, KeyError, TypeError, ValueError):
                messages.info(request, _("El formulario ha caducado. Vuelve a comprobar el ISBN."))
                return redirect("book_create")
            isbn = data["isbn"]
            existing = Edition.objects.select_related("work").filter(isbn=isbn).first()
            if not existing:
                candidates = work_candidates(data)
                form = CoverForm(request.POST, request.FILES, candidates=candidates)
                context.update(stage="cover", data=data, selection=request.POST["selection"], cover_form=form,
                               candidates=candidates, matched_work=form.automatic_work)
                if form.is_valid():
                    saved_image = None
                    try:
                        with transaction.atomic():
                            User.objects.select_for_update().get(pk=request.user.pk)
                            existing = Edition.objects.filter(isbn=isbn).first()
                            if existing:
                                return redirect(add_reading(request.user, existing))
                            # Recompute after acquiring the lock, never trust a posted work ID.
                            fresh = work_candidates(data)
                            allowed = {str(c["work"].pk) for c in fresh}
                            selected = str(form.automatic_work.pk) if form.automatic_work else form.cleaned_data.get("work")
                            if selected and selected != "new" and selected not in allowed:
                                raise ValueError
                            work = resolve_work(data, user=request.user, selected=selected)
                            edition = Edition(work=work, origin="user", created_by=request.user, verified=False,
                                cover_added_by=request.user, cover_added_at=timezone.now(),
                                field_sources={**{key: "user" for key in data}, "cover_image": "user"}, **data)
                            edition.cover_image.save(f"{uuid.uuid4().hex}.jpg", form.cleaned_data["cover"], save=False)
                            saved_image = edition.cover_image
                            edition.save()
                            book = add_reading(request.user, edition)
                        messages.success(request, _("Edición añadida."))
                        return redirect(book)
                    except IntegrityError:
                        if saved_image:
                            saved_image.delete(save=False)
                        existing = Edition.objects.filter(isbn=isbn).first()
                        if not existing:
                            raise
                    except ValueError:
                        if saved_image:
                            saved_image.delete(save=False)
                        form.add_error(None, _("Las coincidencias han cambiado. Vuelve a comprobar los datos."))
                    except Exception:
                        if saved_image:
                            saved_image.delete(save=False)
                        raise
                if not existing:
                    return render(request, "library/manual_edition.html", context)
            # A concurrent creation becomes a choice to reuse; never a duplicate.
            context.update(stage="existing", existing=existing)
            return render(request, "library/manual_edition.html", context)
    if isbn:
        existing = Edition.objects.select_related("work").filter(isbn=isbn).first()
        context.update(isbn=isbn, stage="existing" if existing else "details", existing=existing)
        if request.method == "POST" and request.POST.get("action") == "reuse" and existing:
            with transaction.atomic():
                User.objects.select_for_update().get(pk=request.user.pk)
                book = add_reading(request.user, existing)
            return redirect(book)
        if not existing:
            form = EditionMetadataForm(request.POST if request.method == "POST" and request.POST.get("action") == "details" else None)
            context["metadata_form"] = form
            if form.is_bound and form.is_valid():
                data = {"isbn": isbn, **form.cleaned_data}
                candidates = work_candidates(data)
                cover_form = CoverForm(candidates=candidates)
                context.update(stage="cover", data=data, cover_form=cover_form, candidates=candidates,
                               matched_work=cover_form.automatic_work,
                               selection=signing.dumps({"user": request.user.pk, "data": data}, salt=SALT, compress=True))
    return render(request, "library/manual_edition.html", context)


def cover(request, pk):
    # Only sanitised JPEGs are exposed. Storage paths and original files never are.
    edition = get_object_or_404(Edition, pk=pk)
    if not edition.cover_image:
        raise Http404
    try:
        return FileResponse(edition.cover_image.open("rb"), content_type="image/jpeg")
    except FileNotFoundError:
        raise Http404


@verified_email_required
def add_cover(request, pk):
    book = get_object_or_404(Book.objects.select_related("catalog_edition"), owner=request.user, pk=pk)
    if not book.catalog_edition_id:
        messages.info(request, _("Enlaza primero una edición para añadir su portada."))
        return redirect(book)
    if book.catalog_edition.cover_image:
        messages.info(request, _("Esta edición ya tiene una foto de portada."))
        return redirect(book)
    form = CoverForm(request.POST if request.method == "POST" else None, request.FILES if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        saved_image = None
        try:
            with transaction.atomic():
                edition = Edition.objects.select_for_update().get(pk=book.catalog_edition_id)
                if edition.cover_image:
                    messages.info(request, _("Esta edición ya tiene una foto de portada."))
                    return redirect(book)
                edition.cover_image.save(f"{uuid.uuid4().hex}.jpg", form.cleaned_data["cover"], save=False)
                saved_image = edition.cover_image
                edition.cover_added_by = request.user
                edition.cover_added_at = timezone.now()
                edition.field_sources = {**edition.field_sources, "cover_image": "user"}
                edition.save(update_fields=["cover_image", "cover_added_by", "cover_added_at", "field_sources"])
            messages.success(request, _("Portada añadida."))
            return redirect(book)
        except Exception:
            if saved_image:
                saved_image.delete(save=False)
            raise
    return render(request, "library/cover_form.html", {"form": form, "book": book, "section": "library"})
