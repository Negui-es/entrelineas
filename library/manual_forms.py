from django import forms
from django.core.files.base import ContentFile
from django.utils.translation import gettext_lazy as _
from .catalog import canonical_isbn
from .cover_processing import load_photo, detect_cover, crop_cover, jpeg_bytes


class ISBNForm(forms.Form):
    isbn = forms.CharField(label="ISBN", max_length=25, widget=forms.TextInput(attrs={"inputmode": "text", "autocomplete": "off", "id": "manual-isbn"}))

    def clean_isbn(self):
        value = canonical_isbn(self.cleaned_data["isbn"])
        if not value:
            raise forms.ValidationError(_("Introduce un ISBN válido de 10 o 13 caracteres."))
        return value


class EditionMetadataForm(forms.Form):
    title = forms.CharField(label=_("Título"), max_length=200)
    author = forms.CharField(label=_("Autor o autora"), max_length=160)
    language = forms.ChoiceField(label=_("Idioma"), required=False, choices=[("", "—"), ("es", "Español"), ("en", "English"), ("de", "Deutsch"), ("fr", "Français"), ("it", "Italiano"), ("other", _("Otro idioma"))])
    publisher = forms.CharField(label=_("Editorial"), max_length=200, required=False)
    total_pages = forms.IntegerField(label=_("Páginas"), min_value=1, max_value=100000, required=False)


class CoverForm(forms.Form):
    # A FileField lets us bound bytes and pixels before Pillow decodes the photo.
    cover = forms.FileField(label=_("Foto de portada"), widget=forms.ClearableFileInput(attrs={"accept": "image/jpeg,image/png,image/webp", "data-cover-input": ""}))
    cover_corners = forms.CharField(required=False, widget=forms.HiddenInput, max_length=400)
    cover_rotation = forms.TypedChoiceField(required=False, coerce=int, empty_value=0, choices=[(n, n) for n in (0, 90, 180, 270)], widget=forms.HiddenInput)
    work = forms.ChoiceField(label=_("Obra"), widget=forms.RadioSelect, required=False)

    def __init__(self, *args, candidates=(), **kwargs):
        super().__init__(*args, **kwargs)
        automatic = [item for item in candidates if item["automatic"]]
        self.automatic_work = automatic[0]["work"] if len(automatic) == 1 else None
        if self.automatic_work or not candidates:
            self.fields.pop("work")
        else:
            self.fields["work"].required = True
            self.fields["work"].choices = [(str(c["work"].pk), f'{c["work"].title} · {c["work"].author} ({c["confidence"]} %)') for c in candidates] + [("new", _("Es una obra diferente"))]

    def clean_cover(self):
        return load_photo(self.cleaned_data["cover"])

    def clean(self):
        data = super().clean()
        if "cover" not in data:
            return data
        try:
            photo = data["cover"]
            corners = data.get("cover_corners") or detect_cover(photo)
            if corners:
                photo = crop_cover(photo, corners, data.get("cover_rotation", 0))
            data["cover"] = ContentFile(jpeg_bytes(photo), name="cover.jpg")
        except forms.ValidationError as error:
            self.add_error("cover", error)
        return data
