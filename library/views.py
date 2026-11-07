from django.utils.translation import gettext_lazy as _
from allauth.account.decorators import verified_email_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .forms import BookForm, ReadingNoteForm, ReviewForm, WishForm
from .models import Book, ReadingNote, Review, Wishlist, WishItem, Work, GoodreadsEntry, CSVImportEntry
from .work_identity import current_review, attach_reviews, align_review
from accounts.models import User


def health(request):
    return HttpResponse("ok", content_type="text/plain")


@verified_email_required
def home(request):
    from .dashboard import reading_dashboard
    return render(request, "library/home.html", reading_dashboard(request.user))


@verified_email_required
def reviews(request):
    items = Review.objects.filter(owner=request.user, is_current=True).select_related("book__catalog_edition__work").order_by("-created_at", "-pk")
    total = items.count()
    selected = request.GET.get("filter", "all")
    query = request.GET.get("q", "").strip()
    if selected == "favorites":
        items = items.filter(favorite=True)
    elif selected == "drafts":
        items = items.filter(is_draft=True)
    if query:
        items = items.filter(Q(book__title__icontains=query) | Q(book__author__icontains=query) |
                             Q(text__icontains=query) | Q(memory__icontains=query) | Q(tags__icontains=query))
    reading = request.user.books.filter(status=Book.Status.READING).select_related("catalog_edition__work").first()
    return render(request, "library/reviews.html", {
        "section": "reviews", "page_obj": Paginator(items, 12).get_page(request.GET.get("page")),
        "total": total, "selected": selected, "query": query, "reading": reading,
    })


@verified_email_required
def library(request):
    books = request.user.books.select_related("review", "catalog_edition__work").order_by("-created_at", "-pk")
    status = request.GET.get("status", "")
    query = request.GET.get("q", "").strip()
    if status in Book.Status.values:
        books = books.filter(status=status)
    if query:
        books = books.filter(Q(title__icontains=query) | Q(author__icontains=query))
    page = Paginator(books, 12).get_page(request.GET.get("page"))
    page.object_list = attach_reviews(page.object_list)
    return render(request, "library/library.html", {
        "section": "library", "page_obj": page,
        "statuses": Book.Status.choices, "selected": status, "query": query,
    })


@verified_email_required
def book_edit(request, pk=None):
    book = get_object_or_404(Book, owner=request.user, pk=pk) if pk else None
    form = BookForm(request.POST or None, instance=book)
    if request.method == "POST" and form.is_valid():
        book = form.save(commit=False)
        book.owner = request.user
        book.save()
        messages.success(request, _("Libro guardado."))
        return redirect(book)
    return render(request, "library/book_form.html", {"form": form, "book": book, "section": "library"})


@verified_email_required
def book_detail(request, pk):
    book = get_object_or_404(Book.objects.select_related("review", "catalog_edition__work"), owner=request.user, pk=pk)
    return render(request, "library/book_detail.html", {
        "book": book, "review": current_review(book), "note_form": ReadingNoteForm(book=book),
        "previous_reviews": Review.objects.filter(owner=request.user, work_id=book.catalog_edition.work_id, is_current=False) if book.catalog_edition_id else [],
        "notes": book.notes.all(), "section": "library",
    })


@verified_email_required
def review_edit(request, pk=None):
    review = get_object_or_404(Review.objects.select_related("book"), owner=request.user, pk=pk) if pk else None
    book = review.book if review else None
    book_id = request.GET.get("book") if not review else None
    if book_id:
        try:
            book_id = int(book_id)
        except (ValueError, TypeError):
            raise Http404(_("Libro no encontrado"))
        book = get_object_or_404(Book, owner=request.user, pk=book_id)
        existing = current_review(book)
        if existing:
            return redirect("review_edit", pk=existing.pk)
    # Bibliography is created through ISBN lookup/import, never through a review.
    if not book:
        return redirect("catalog_search")
    book_form = None
    form = ReviewForm(request.POST or None, instance=review)
    if request.method == "POST":
        review_valid = form.is_valid()
        if review_valid:
            with transaction.atomic():
                User.objects.select_for_update().get(pk=request.user.pk)
                review = form.save(commit=False)
                work_id = book.catalog_edition.work_id if book.catalog_edition_id else None
                if work_id:
                    Work.objects.select_for_update().get(pk=work_id)
                existing = current_review(book)
                if not review.pk and existing:
                    review.pk, review.book_id = existing.pk, existing.book_id
                else:
                    review.book = book
                review.owner = request.user
                review.work_id = work_id
                review.is_current = True
                if work_id:
                    Review.objects.filter(owner=request.user, work_id=work_id, is_current=True).exclude(pk=review.pk).update(is_current=False)
                review.is_draft = request.POST.get("action") != "save"
                review.visibility = "private"
                review.save()
            messages.success(request, _("Borrador guardado.") if review.is_draft else _("Reseña guardada."))
            return redirect(book)
    return render(request, "library/review_form.html", {
        "form": form, "book_form": book_form, "book": book, "review": review, "section": "reviews",
    })


@verified_email_required
@require_POST
def favorite(request, pk):
    review = get_object_or_404(Review, owner=request.user, pk=pk)
    review.favorite = not review.favorite
    review.save(update_fields=["favorite"])
    return redirect("reviews")


@verified_email_required
@require_POST
def note_add(request, pk):
    book = get_object_or_404(Book, owner=request.user, pk=pk)
    form = ReadingNoteForm(request.POST, book=book)
    if form.is_valid():
        note = form.save(commit=False)
        note.book = book
        note.save()
        messages.success(request, _("Nota guardada."))
        return redirect(f"{book.get_absolute_url()}#notas")
    return render(request, "library/book_detail.html", {
        "book": book, "review": current_review(book), "note_form": form, "notes": book.notes.all(), "section": "library",
    }, status=400)


@verified_email_required
@require_POST
def note_delete(request, pk):
    note = get_object_or_404(ReadingNote, book__owner=request.user, pk=pk)
    book = note.book
    note.delete()
    messages.success(request, _("Nota eliminada."))
    return redirect(f"{book.get_absolute_url()}#notas")


@verified_email_required
def book_delete(request, pk):
    book = get_object_or_404(Book, owner=request.user, pk=pk)
    if request.method == "POST":
        with transaction.atomic():
            User.objects.select_for_update().get(pk=request.user.pk)
            review = getattr(book, "review", None)
            if review and review.work_id:
                other = request.user.books.filter(catalog_edition__work_id=review.work_id, review__isnull=True).exclude(pk=book.pk).first()
                if other:
                    Review.objects.filter(pk=review.pk).update(book=other)
            book.delete()
            if review and review.work_id and not Review.objects.filter(owner=request.user, work_id=review.work_id, is_current=True).exists():
                previous = Review.objects.filter(owner=request.user, work_id=review.work_id).first()
                if previous:
                    Review.objects.filter(pk=previous.pk).update(is_current=True)
        messages.success(request, _("Libro eliminado."))
        return redirect("library")
    return render(request, "library/delete.html", {"item": book, "cancel_url": book.get_absolute_url(), "section": "library"})


@verified_email_required
def wishlist(request):
    listing, unused = Wishlist.objects.get_or_create(owner=request.user)
    items = listing.items.select_related("catalog_edition__work").order_by("-created_at", "-pk")
    query = request.GET.get("q", "").strip()
    if query:
        items = items.filter(Q(title__icontains=query) | Q(author__icontains=query))
    share_url = request.build_absolute_uri(reverse("wishlist_shared", args=[listing.share_token])) if listing.share_token else None
    return render(request, "library/wishlist.html", {
        "section": "wishes", "wishlist": listing, "page_obj": Paginator(items, 12).get_page(request.GET.get("page")),
        "share_url": share_url, "query": query,
    })


@verified_email_required
def wish_edit(request, pk=None):
    listing, unused = Wishlist.objects.get_or_create(owner=request.user)
    item = get_object_or_404(WishItem, wishlist=listing, pk=pk) if pk else None
    form = WishForm(request.POST or None, instance=item)
    if request.method == "POST" and form.is_valid():
        item = form.save(commit=False)
        item.wishlist = listing
        item.save()
        messages.success(request, _("Deseo guardado."))
        return redirect("wishlist")
    return render(request, "library/wish_form.html", {"form": form, "item": item, "section": "wishes"})


@verified_email_required
def wish_delete(request, pk):
    item = get_object_or_404(WishItem, wishlist__owner=request.user, pk=pk)
    if request.method == "POST":
        item.delete()
        messages.success(request, _("Deseo eliminado."))
        return redirect("wishlist")
    return render(request, "library/delete.html", {"item": item, "cancel_url": reverse("wishlist"), "section": "wishes"})


@verified_email_required
@require_POST
def wish_receive(request, pk):
    from .ranking import normalize

    with transaction.atomic():
        User.objects.select_for_update().get(pk=request.user.pk)
        item = get_object_or_404(WishItem.objects.select_related("catalog_edition__work"), pk=pk, wishlist__owner=request.user)
        metadata = item.metadata
        books = request.user.books.select_related("catalog_edition__work")
        book = books.filter(catalog_edition=item.catalog_edition).first() if item.catalog_edition_id else None
        if not book:
            # An unspecified edition can reuse a known reading. Two explicitly
            # different editions remain separate, retaining their own covers.
            candidates = books.filter(catalog_edition__isnull=True) if item.catalog_edition_id else books
            book = next((candidate for candidate in candidates
                         if normalize(candidate.metadata.title) == normalize(metadata.title)
                         and normalize(candidate.metadata.author) == normalize(metadata.author)), None)
            if book and item.catalog_edition_id:
                from .goodreads_catalog import link_existing
                if not link_existing(book, item.catalog_edition):
                    book = None
        if not book:
            pages = item.catalog_edition.total_pages if item.catalog_edition_id else None
            book = Book.objects.create(owner=request.user, catalog_edition=item.catalog_edition,
                title=metadata.title, author=metadata.author,
                isbn=(item.catalog_edition.isbn or "") if item.catalog_edition_id else "",
                total_pages=pages or None, color=item.color, status=Book.Status.PENDING)
        note = str(_("Recibido como regalo desde la lista de deseos."))
        if item.edition:
            note += "\n" + str(_("Preferencia de edición: %(edition)s")) % {"edition": item.edition}
        ReadingNote.objects.create(book=book, text=note)
        # Keep import identities so reuploading an old export cannot recreate
        # a wish that has already been received.
        for model in (GoodreadsEntry, CSVImportEntry):
            model.objects.filter(owner=request.user, wish=item).update(wish=None, book=book)
        item.delete()
    messages.success(request, _("Regalo recibido. El libro está en tu biblioteca."))
    return redirect("wishlist")


@verified_email_required
@require_POST
def wishlist_sharing(request):
    listing, unused = Wishlist.objects.get_or_create(owner=request.user)
    if request.POST.get("action") == "enable":
        listing.enable_sharing()
        messages.success(request, _("Enlace para compartir activado."))
    else:
        listing.revoke_sharing()
        messages.success(request, _("Enlace para compartir desactivado."))
    return redirect("wishlist")


def wishlist_shared(request, token):
    listing = get_object_or_404(Wishlist.objects.select_related("owner"), share_token=token)
    return render(request, "library/shared.html", {
        "display_name": listing.owner.display_name, "items": listing.items.select_related("catalog_edition__work"),
    })
