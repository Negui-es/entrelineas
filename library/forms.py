from django.utils.translation import gettext_lazy as _
from django import forms
from .models import Book, ReadingNote, Review, WishItem


class BookForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.catalog_edition_id and self.instance.metadata is not self.instance:
            for name in ("title", "author", "isbn", "total_pages"):
                self.fields[name].disabled = True
                self.fields[name].initial = getattr(self.instance.metadata, name)
                self.initial[name] = getattr(self.instance.metadata, name)

    class Meta:
        model = Book
        fields = ["title", "author", "isbn", "color", "status", "total_pages", "current_page", "started_at", "finished_at"]
        widgets = {"started_at": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
                   "finished_at": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}


class ReviewForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["tags"].help_text = _("Separa las etiquetas con comas.")
        self.fields["rating"].help_text = _("De 0,5 a 5 estrellas. Puedes usar decimales, por ejemplo 3,5 o 4,25.")

    class Meta:
        model = Review
        fields = ["rating", "text", "best", "worst", "memory", "recommended_for", "tags", "contains_spoilers", "favorite"]
        widgets = {
            "rating": forms.NumberInput(attrs={"min": "0.5", "max": "5", "step": "0.01", "inputmode": "decimal"}),
            "text": forms.Textarea(attrs={"rows": 4}),
            "best": forms.Textarea(attrs={"rows": 2}),
            "worst": forms.Textarea(attrs={"rows": 2}),
            "memory": forms.Textarea(attrs={"rows": 2}),
        }
        labels = {"text": _("Reseña"), "worst": _("Lo mejorable"), "memory": _("Qué recordar"), "recommended_for": _("Recomendado para")}

    def clean(self):
        data = super().clean()
        if self.data.get("action") == "save" and not any(data.get(k, "").strip() for k in ("text", "best", "worst", "memory")):
            raise forms.ValidationError(_("Escribe al menos una idea o guarda la reseña como borrador."))
        return data


class ReadingNoteForm(forms.ModelForm):
    class Meta:
        model = ReadingNote
        fields = ["text", "page"]
        widgets = {"text": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, book=None, **kwargs):
        self.book = book
        super().__init__(*args, **kwargs)

    def clean_page(self):
        page = self.cleaned_data.get("page")
        if page is not None and self.book and self.book.total_pages and page > self.book.total_pages:
            raise forms.ValidationError(_("La página supera el total del libro."))
        return page


class WishForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.catalog_edition_id and self.instance.metadata is not self.instance:
            for name in ("title", "author"):
                self.fields[name].disabled = True
                self.initial[name] = getattr(self.instance.metadata, name)

    class Meta:
        model = WishItem
        fields = ["title", "author", "edition", "priority", "purchase_url", "color"]

    def clean_purchase_url(self):
        url = self.cleaned_data["purchase_url"]
        if url and not url.lower().startswith(("https://", "http://")):
            raise forms.ValidationError(_("Utiliza un enlace http o https."))
        return url
