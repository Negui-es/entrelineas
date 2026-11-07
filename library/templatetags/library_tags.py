from django.utils.translation import gettext_lazy as _
from django import template
from django.templatetags.static import static
from django.utils.html import format_html
from django.utils.formats import number_format
from decimal import Decimal

register = template.Library()


@register.filter
def book_language(value):
    from django.utils.translation import get_language_info
    from library.ranking import language
    code = language(value)
    try:
        return get_language_info(code)["name_translated"]
    except KeyError:
        return value


@register.filter
def metadata_label(value):
    return {"total_pages": _("Páginas"), "publisher": _("Editorial"), "publication_date": _("Publicación"),
            "language": _("Idioma")}.get(value, value)


@register.filter
def catalog_label(value):
    from library.catalog import PROVIDERS
    return PROVIDERS.get(value, value)

@register.simple_tag
def icon(name, css=""):
    return format_html('<svg class="icon {}" width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><use href="{}#{}"></use></svg>', css, static("icons.svg"), name)

@register.filter
def stars(value):
    if not value:
        return _("Sin valorar")
    rating = max(Decimal("0"), min(Decimal("5"), Decimal(str(value))))
    label = number_format(rating, decimal_pos=2).rstrip("0").rstrip(",.")
    return format_html(
        '<span class="fractional-stars" role="img" aria-label="{} / 5">'
        '<span aria-hidden="true">☆☆☆☆☆</span>'
        '<span class="fractional-stars-fill" style="width: {}%" aria-hidden="true">★★★★★</span>'
        '</span> <span class="rating-number">{}/5</span>', label, str(rating * 20), label)

@register.simple_tag(takes_context=True)
def page_url(context, **kwargs):
    query = context["request"].GET.copy()
    for key, value in kwargs.items():
        query[key] = value
    return "?" + query.urlencode()
