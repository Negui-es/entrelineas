from django.utils.translation import gettext_lazy as _
from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.functions import Lower


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError(_("El email es obligatorio."))
        user = self.model(email=self.normalize_email(email).lower(), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        if not extra_fields["is_staff"] or not extra_fields["is_superuser"]:
            raise ValueError(_("Un administrador debe tener is_staff e is_superuser."))
        return self.create_user(email, password, **extra_fields)


class User(AbstractUser):
    class Theme(models.TextChoices):
        AUTO = "auto", _("Automático")
        LIGHT = "light", _("Claro")
        DARK = "dark", _("Oscuro")

    username = None
    email = models.EmailField(_("email"), unique=True)
    display_name = models.CharField(_("nombre visible"), max_length=60)
    theme = models.CharField(_("Apariencia"), max_length=5, choices=Theme.choices, default=Theme.AUTO)
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["display_name"]
    objects = UserManager()

    class Meta:
        constraints = [models.UniqueConstraint(Lower("email"), name="unique_email_case_insensitive")]

    def save(self, *args, **kwargs):
        self.email = self.email.lower().strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.display_name or self.email

    @property
    def initial(self):
        return (self.display_name or "L")[0].upper()
