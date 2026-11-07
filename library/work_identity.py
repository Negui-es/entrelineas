"""Resolve shared works without mixing edition data or private reviews."""
import hashlib
import uuid
from django.db import transaction
from django.utils.translation import gettext as _
from .matching import author_tokens, same_work_confidence, GENERIC_TITLES
from .models import Work, Review, Edition
from .ranking import normalize


def fingerprint(data):
    value = normalize(data["title"]) + "|" + " ".join(author_tokens(data))
    return hashlib.sha256(value.encode()).hexdigest()


def work_data(work):
    provider, _, key = work.identity.partition(":")
    return {"title": work.title, "author": work.author, "provider": provider, "work_key": key}


def matching_head(data, work):
    head = work_data(work)
    identity = str(data.get("provider", "")) + ":" + str(data.get("work_key", ""))
    if any(alias.identity == identity for alias in work.aliases.all()):
        head.update(provider=data["provider"], work_key=data["work_key"])
    return head


def work_candidates(data):
    candidates = []
    for work in Work.objects.filter(merged_into__isnull=True).exclude(origin="legacy").prefetch_related("editions", "aliases").order_by("created_at", "pk"):
        head = matching_head(data, work)
        report = same_work_confidence(data, head)
        if report["score"] < 60:
            continue
        # Complete-link rule also applies when persisting identities.
        reports = [report, *[same_work_confidence(data, {"title": e.title, "author": e.author,
            "provider": head["provider"], "work_key": head["work_key"]}) for e in work.editions.all()]]
        score = min(r["score"] for r in reports)
        if score >= 60:
            candidates.append({"work": work, "confidence": score, "automatic": all(r["automatic"] for r in reports)})
    return sorted(candidates, key=lambda item: (-item["confidence"], item["work"].created_at, str(item["work"].pk)))


def resolve_work(data, *, user=None, selected=None):
    candidates = work_candidates(data)
    if selected and selected != "new":
        candidate = next(item["work"] for item in candidates if str(item["work"].pk) == selected)
        work = Work.objects.select_for_update().get(pk=candidate.pk)
        while work.merged_into_id:
            work = Work.objects.select_for_update().get(pk=work.merged_into_id)
        return work
    automatic = [item for item in candidates if item["automatic"]]
    if not selected and automatic:
        works = [item["work"] for item in automatic]
        if all(same_work_confidence(work_data(a), work_data(b))["automatic"] for i, a in enumerate(works) for b in works[i+1:]):
            return merge_works(works)
    reliable_title = normalize(data["title"]) not in GENERIC_TITLES and len(author_tokens(data)) >= 2
    identity = ("user:" + (fingerprint(data) if reliable_title and selected != "new" else uuid.uuid4().hex)) if user else data["provider"] + ":" + data["work_key"]
    existing = Work.objects.filter(identity=identity).first()
    if existing:
        while existing.merged_into_id:
            existing = existing.merged_into
        if not same_work_confidence(data, work_data(existing))["automatic"]:
            from .catalog import CatalogError
            raise CatalogError(_("El identificador de obra tiene datos contradictorios. Revisa la edición."))
        return existing
    work, unused = Work.objects.get_or_create(identity=identity, defaults={
        "title": data["title"], "author": data["author"], "origin": "user" if user else "external", "created_by": user})
    return work


@transaction.atomic
def merge_works(works):
    """Retain former IDs as aliases and keep conflicting historical reviews."""
    ids = [w.pk for w in works]
    locked = list(Work.objects.select_for_update().filter(pk__in=ids, merged_into__isnull=True).order_by("created_at", "pk"))
    if not locked:
        root = Work.objects.get(pk=ids[0])
        return root.merged_into or root
    root, *others = locked
    if not others:
        return root
    members = [work_data(w) for w in locked]
    for work in locked:
        head = work_data(work)
        members.extend({**head, "title": e.title, "author": e.author} for e in work.editions.all())
    if not all(same_work_confidence(a, b)["automatic"] for i, a in enumerate(members) for b in members[i+1:]):
        raise ValueError("Incompatible works")
    all_ids = [w.pk for w in locked]
    latest = {}
    for review in Review.objects.filter(work_id__in=all_ids).order_by("-updated_at", "-pk"):
        latest.setdefault(review.owner_id, review.pk)
    Review.objects.filter(work_id__in=all_ids).update(is_current=False)
    Edition.objects.filter(work__in=others).update(work=root)
    Review.objects.filter(work__in=others).update(work=root)
    Review.objects.filter(pk__in=latest.values()).update(is_current=True)
    Work.objects.filter(merged_into__in=others).update(merged_into=root)
    Work.objects.filter(pk__in=[w.pk for w in others]).update(merged_into=root)
    return root


def current_review(book):
    return book.work_review


def attach_reviews(books):
    books = list(books)
    work_ids = {b.catalog_edition.work_id for b in books if b.catalog_edition_id}
    owner_ids = {b.owner_id for b in books}
    reviews = {(r.owner_id, r.work_id): r for r in Review.objects.filter(owner_id__in=owner_ids, work_id__in=work_ids, is_current=True)}
    for book in books:
        if book.catalog_edition_id:
            book._work_review = reviews.get((book.owner_id, book.catalog_edition.work_id))
    return books


def align_review(book):
    """Keep an existing personal review when its reading changes edition."""
    review = getattr(book, "review", None)
    if not review or not book.catalog_edition_id:
        return
    work_id = book.catalog_edition.work_id
    if review.work_id == work_id:
        return
    old_work_id = review.work_id
    Review.objects.filter(pk=review.pk).update(is_current=False, work_id=work_id, owner_id=book.owner_id)
    newest = Review.objects.filter(owner_id=book.owner_id, work_id=work_id).order_by("-updated_at", "-pk").first()
    Review.objects.filter(owner_id=book.owner_id, work_id=work_id).update(is_current=False)
    Review.objects.filter(pk=newest.pk).update(is_current=True)
    if old_work_id:
        previous = Review.objects.filter(owner_id=book.owner_id, work_id=old_work_id).first()
        Review.objects.filter(owner_id=book.owner_id, work_id=old_work_id).update(is_current=False)
        if previous:
            Review.objects.filter(pk=previous.pk).update(is_current=True)
