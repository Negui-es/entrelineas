"""Private reading statistics, derived only from recorded reading dates."""
from datetime import date

from django.db.models import Avg, Count, Q
from django.db.models.functions import TruncMonth
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.translation import gettext as _

from .models import Book, Review


def reading_dashboard(user):
    today = timezone.localdate()
    books = user.books.select_related("catalog_edition__work")
    reviews = Review.objects.filter(owner=user, is_current=True)
    completed = books.filter(status=Book.Status.FINISHED)
    this_year = completed.filter(finished_at__gte=date(today.year, 1, 1), finished_at__lte=today)
    count = this_year.count()
    monthly = {row["month"].month: row["count"] for row in this_year.order_by().annotate(
        month=TruncMonth("finished_at")).values("month").annotate(count=Count("pk"))}
    peak = max(monthly.values(), default=1)
    months = []
    for month in range(1, 13):
        day = date(today.year, month, 1)
        value = monthly.get(month, 0)
        months.append({"label": date_format(day, "M"), "name": date_format(day, "F"),
                       "count": value, "height": round(value / peak * 100),
                       "future": month > today.month, "current": month == today.month})
    # An edition's pages are authoritative except for private legacy/manual records.
    pages = 0
    timed_days = []
    for book in this_year:
        pages += book.metadata.total_pages or 0
        if book.started_at and book.started_at <= book.finished_at:
            timed_days.append((book.finished_at - book.started_at).days + 1)
    stats = books.aggregate(total=Count("pk"), reading=Count("pk", filter=Q(status=Book.Status.READING)),
                            pending=Count("pk", filter=Q(status=Book.Status.PENDING)),
                            finished=Count("pk", filter=Q(status=Book.Status.FINISHED)),
                            abandoned=Count("pk", filter=Q(status=Book.Status.ABANDONED)))
    states = [("finished", _("Terminados")), ("reading", _("Leyendo")),
              ("pending", _("Pendientes")), ("abandoned", _("Abandonados"))]
    return {
        "section": "home", "year": today.year, "stats": stats, "year_count": count,
        "year_pages": pages, "review_count": reviews.count(),
        "average_rating": reviews.filter(is_draft=False).aggregate(value=Avg("rating"))["value"],
        "months": months, "pace": round(count / today.month, 1),
        "average_days": round(sum(timed_days) / len(timed_days)) if timed_days else None,
        "undated_count": completed.filter(finished_at__isnull=True).count(),
        "currently_reading": books.filter(status=Book.Status.READING).order_by("-updated_at", "-pk")[:3],
        "favorites": reviews.filter(favorite=True, is_draft=False).select_related(
            "book__catalog_edition__work").order_by("-rating", "-updated_at", "-pk")[:4],
        "review_prompt": completed.exclude(review__is_current=True).exclude(
            catalog_edition__work_id__in=reviews.exclude(work_id=None).values("work_id")
        ).order_by("-finished_at", "-pk").first(),
        "states": [{"key": key, "label": label, "count": stats[key],
                    "width": round(stats[key] / stats["total"] * 100, 2) if stats["total"] else 0}
                   for key, label in states],
    }
