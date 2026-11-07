from django.conf import settings


def navigation(request):
    context = {"registration_open": settings.REGISTRATION_OPEN}
    if request.user.is_authenticated:
        context["nav_review_count"] = request.user.work_reviews.filter(is_current=True).count()
    return context
