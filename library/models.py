from django.utils.translation import gettext_lazy as _
import secrets
import uuid
from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.urls import reverse


class Work(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    identity = models.CharField(max_length=300, unique=True)
    title = models.CharField(max_length=200)
    author = models.CharField(max_length=160)
    origin = models.CharField(max_length=12, default="external", choices=[("external", "external"), ("user", "user"), ("legacy", "legacy")])
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_works")
    verified = models.BooleanField(default=False)
    merged_into = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="aliases")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


class Edition(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    work = models.ForeignKey(Work, on_delete=models.PROTECT, related_name="editions")
    title = models.CharField(max_length=200)
    author = models.CharField(max_length=160)
    isbn = models.CharField(max_length=13, unique=True, null=True, blank=True)
    publisher = models.CharField(max_length=200, blank=True)
    publication_date = models.CharField(max_length=80, blank=True)
    language = models.CharField(max_length=40, blank=True)
    total_pages = models.PositiveIntegerField(null=True, blank=True)
    cover_url = models.URLField(max_length=500, blank=True)
    cover_image = models.ImageField(upload_to="covers/", blank=True)
    cover_added_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="uploaded_covers")
    cover_added_at = models.DateTimeField(null=True, blank=True)
    origin = models.CharField(max_length=12, default="external", choices=[("external", "external"), ("user", "user"), ("legacy", "legacy")])
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_editions")
    verified = models.BooleanField(default=False)
    synopsis = models.TextField(blank=True)
    field_sources = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self):
        return self.title

    @property
    def display_cover_url(self):
        if self.cover_image:
            return reverse("edition_cover", args=[self.pk])
        if self.cover_url:
            return self.cover_url
        # Covers may be shared within a conservatively matched work; edition
        # ISBN, publisher and page count remain those of this edition.
        other = self.work.editions.exclude(pk=self.pk).filter(
            Q(cover_image__gt="") | Q(cover_url__gt="")).order_by("-verified", "created_at", "pk").first()
        if other:
            return reverse("edition_cover", args=[other.pk]) if other.cover_image else other.cover_url
        return ""


class CatalogSource(models.Model):
    edition = models.ForeignKey(Edition, on_delete=models.CASCADE, related_name="sources")
    provider = models.CharField(max_length=20)
    external_id = models.CharField(max_length=200)
    url = models.URLField(max_length=500)
    metadata = models.JSONField(default=dict)
    retrieved_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["provider", "external_id"], name="unique_external_edition")]


class Book(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", _("Pendiente")
        READING = "reading", _("Leyendo")
        FINISHED = "finished", _("Terminado")
        ABANDONED = "abandoned", _("Abandonado")

    class Color(models.TextChoices):
        GOLD = "gold", _("Ocre")
        BLUE = "blue", _("Azul")
        ROSE = "rose", _("Rosa")
        GREEN = "green", _("Verde")

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="books")
    catalog_edition = models.ForeignKey(Edition, null=True, blank=True, on_delete=models.PROTECT, related_name="readings")
    # Private legacy snapshots are retained for lossless migration and offline
    # compatibility. Linked records render Edition as their bibliographic source.
    title = models.CharField(_("título"), max_length=200)
    author = models.CharField(_("autor o autora"), max_length=160)
    isbn = models.CharField(_("ISBN"), max_length=17, blank=True)
    color = models.CharField(_("color de portada"), max_length=10, choices=Color, default=Color.GOLD)
    status = models.CharField(_("estado de lectura"), max_length=12, choices=Status, default=Status.PENDING)
    total_pages = models.PositiveIntegerField(_("páginas totales"), null=True, blank=True, validators=[MinValueValidator(1)])
    current_page = models.PositiveIntegerField(_("página actual"), default=0)
    started_at = models.DateField(_("inicio de lectura"), null=True, blank=True)
    finished_at = models.DateField(_("fin de lectura"), null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.CheckConstraint(condition=Q(total_pages__isnull=True) | Q(total_pages__gte=1), name="positive_total_pages"),
            models.CheckConstraint(condition=Q(total_pages__isnull=True) | Q(current_page__lte=F("total_pages")), name="page_within_book"),
            models.CheckConstraint(condition=Q(started_at__isnull=True) | Q(finished_at__isnull=True) | Q(finished_at__gte=F("started_at")), name="valid_reading_dates"),
        ]

    def clean(self):
        if self.total_pages is not None and self.current_page > self.total_pages:
            raise ValidationError({"current_page": _("La página actual no puede superar el total.")})
        if self.started_at and self.finished_at and self.finished_at < self.started_at:
            raise ValidationError({"finished_at": _("La fecha final debe ser posterior al inicio.")})

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("book_detail", args=[self.pk])

    @property
    def progress(self):
        pages = self.metadata.total_pages
        return round(self.current_page / pages * 100) if pages else 0

    @property
    def metadata(self):
        edition = self.catalog_edition
        return edition if edition and not edition.work.identity.startswith(("legacy:", "manual:")) else self

    @property
    def cover_url(self):
        return self.catalog_edition.display_cover_url if self.catalog_edition_id else ""

    @property
    def work_review(self):
        if hasattr(self, "_work_review"):
            return self._work_review
        if self.catalog_edition_id:
            return Review.objects.filter(owner_id=self.owner_id, work_id=self.catalog_edition.work_id, is_current=True).first()
        return getattr(self, "review", None)


class Review(models.Model):
    book = models.OneToOneField(Book, on_delete=models.CASCADE, related_name="review")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="work_reviews")
    work = models.ForeignKey(Work, null=True, blank=True, on_delete=models.PROTECT, related_name="reviews")
    is_current = models.BooleanField(default=True, editable=False)
    rating = models.DecimalField(_("valoración"), max_digits=3, decimal_places=2, null=True, blank=True,
                                 validators=[MinValueValidator(Decimal("0.5")), MaxValueValidator(5)])
    text = models.TextField(_("lo que me dejó"), blank=True)
    best = models.TextField(_("lo mejor"), blank=True)
    worst = models.TextField(_("lo que no me convenció"), blank=True)
    memory = models.TextField(_("para mi yo del futuro"), blank=True)
    recommended_for = models.CharField(_("a quién se lo recomendaría"), max_length=240, blank=True)
    tags = models.CharField(_("etiquetas"), max_length=200, blank=True, help_text=_("Separadas por comas: para releer, me hizo pensar…"))
    contains_spoilers = models.BooleanField(_("contiene spoilers"), default=False)
    favorite = models.BooleanField(_("favorita"), default=False)
    is_draft = models.BooleanField(_("borrador"), default=True)
    # Only private reviews are supported in this release. Future audiences need
    # explicit membership checks and an explicit publication action.
    visibility = models.CharField(max_length=12, choices=[("private", _("Solo yo"))], default="private", editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "work"], condition=Q(is_current=True, work__isnull=False), name="one_current_review_per_work"),
            models.CheckConstraint(condition=Q(rating__isnull=True) | Q(rating__gte=Decimal("0.5"), rating__lte=5), name="review_rating_range"),
            models.CheckConstraint(condition=Q(visibility="private"), name="private_reviews_only"),
        ]

    @property
    def tag_list(self):
        return [tag.strip() for tag in self.tags.split(",") if tag.strip()][:6]

    def save(self, *args, **kwargs):
        if not self.owner_id:
            self.owner_id = self.book.owner_id
        if not self.work_id and self.book.catalog_edition_id:
            self.work_id = self.book.catalog_edition.work_id
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Reseña de {self.book.title}"


class DocumentImportEntry(models.Model):
    """Per-owner provenance prevents duplicate imports and retains source precision."""
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="document_imports")
    source_key = models.CharField(max_length=200)
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["owner", "source_key"], name="unique_document_import")]


class CSVImportEntry(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    source_id = models.UUIDField()
    book = models.ForeignKey(Book, null=True, blank=True, on_delete=models.CASCADE, related_name="csv_imports")
    wish = models.ForeignKey("WishItem", null=True, blank=True, on_delete=models.CASCADE, related_name="csv_imports")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["owner", "source_id"], name="unique_native_csv_import"),
            models.CheckConstraint(condition=(Q(book__isnull=False, wish__isnull=True) |
                                              Q(book__isnull=True, wish__isnull=False)), name="native_csv_one_destination"),
        ]


class GoodreadsEntry(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    external_id = models.CharField(max_length=40)
    book = models.ForeignKey(Book, null=True, blank=True, on_delete=models.CASCADE)
    wish = models.ForeignKey("WishItem", null=True, blank=True, on_delete=models.CASCADE)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["owner", "external_id"], name="unique_goodreads_import"),
            models.CheckConstraint(condition=(Q(book__isnull=False, wish__isnull=True) |
                                              Q(book__isnull=True, wish__isnull=False)), name="goodreads_one_destination"),
        ]


class ReadingNote(models.Model):
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="notes")
    text = models.TextField(_("nota personal"))
    page = models.PositiveIntegerField(_("página"), null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class Wishlist(models.Model):
    owner = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="wishlist")
    share_token = models.CharField(max_length=64, unique=True, null=True, blank=True, editable=False)

    def enable_sharing(self):
        if not self.share_token:
            self.share_token = secrets.token_urlsafe(32)
            self.save(update_fields=["share_token"])

    def revoke_sharing(self):
        self.share_token = None
        self.save(update_fields=["share_token"])


class WishItem(models.Model):
    wishlist = models.ForeignKey(Wishlist, on_delete=models.CASCADE, related_name="items")
    catalog_edition = models.ForeignKey(Edition, null=True, blank=True, on_delete=models.PROTECT, related_name="wishes")
    title = models.CharField(_("título"), max_length=200)
    author = models.CharField(_("autor o autora"), max_length=160)
    edition = models.CharField(_("edición preferida"), max_length=160, blank=True)
    purchase_url = models.URLField(_("enlace de compra"), blank=True)
    priority = models.CharField(_("prioridad"), max_length=10, choices=[("high", _("Me hace mucha ilusión")), ("normal", _("Me apetece")), ("low", _("Algún día"))], default="normal")
    color = models.CharField(_("color de portada"), max_length=10, choices=Book.Color, default=Book.Color.BLUE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title

    @property
    def metadata(self):
        edition = self.catalog_edition
        return edition if edition and not edition.work.identity.startswith(("legacy:", "manual:")) else self

    @property
    def cover_url(self):
        return self.catalog_edition.display_cover_url if self.catalog_edition_id else ""
