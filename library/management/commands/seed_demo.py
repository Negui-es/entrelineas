import secrets
from datetime import date

from allauth.account.models import EmailAddress
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import User
from library.models import Book, ReadingNote, Review, Wishlist, WishItem


class Command(BaseCommand):
    help = "Crea datos de ejemplo en una cuenta local independiente. Solo en desarrollo."

    def add_arguments(self, parser):
        parser.add_argument("--reset-password", action="store_true")

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Los datos de ejemplo solo están disponibles con DEBUG=true.")
        email = "demo@example.test"
        user, created = User.objects.get_or_create(email=email, defaults={"display_name": "Lector de ejemplo"})
        if created or options["reset_password"]:
            password = secrets.token_urlsafe(14)
            user.set_password(password)
            user.save()
            self.stdout.write(f"Cuenta local de ejemplo: {email}\nContraseña: {password}")
        else:
            self.stdout.write(f"La cuenta {email} ya existe. Usa --reset-password para cambiar su contraseña.")
        EmailAddress.objects.update_or_create(user=user, email=email, defaults={"verified": True, "primary": True})
        data = [
            ("La sombra del viento", "Carlos Ruiz Zafón", "gold", 5, True, False,
             "Una Barcelona en la que me quedaría a vivir. Misterio, libros y personajes que cuesta dejar atrás.",
             "La atmósfera y el cariño que acabas sintiendo por sus personajes.", "Algunas coincidencias me parecieron demasiado convenientes.",
             "La sensación de descubrir un secreto al entrar en una librería.", "Para releer"),
            ("El infinito en un junco", "Irene Vallejo", "blue", 4, False, False,
             "Lo terminé mirando mi estantería de otra manera. Una historia de los libros que se siente muy humana.",
             "Las conexiones entre historias antiguas y preocupaciones actuales.", "Lo disfruté más leyendo pequeños fragmentos.",
             "Cada libro que conservamos tiene detrás muchas personas.", "Me hizo pensar"),
            ("La ridícula idea de no volver a verte", "Rosa Montero", "rose", None, False, True,
             "Aún estoy ordenando lo que me ha dejado. Hay páginas a las que quiero volver.", "", "", "", ""),
        ]
        for title, author, color, rating, favorite, draft, text, best, worst, memory, tags in data:
            book, _ = Book.objects.get_or_create(owner=user, title=title, defaults={"author": author, "color": color, "status": "finished", "finished_at": date(2026, 10, 18)})
            Review.objects.get_or_create(book=book, defaults={"rating": rating, "favorite": favorite, "is_draft": draft, "text": text, "best": best, "worst": worst, "memory": memory, "tags": tags})
        book, _ = Book.objects.get_or_create(owner=user, title="Un lugar soleado para gente sombría", defaults={"author": "Mariana Enriquez", "color": "rose", "status": "reading", "total_pages": 260, "current_page": 112})
        ReadingNote.objects.get_or_create(book=book, text="La atmósfera de este relato me ha dejado pensando.", defaults={"page": 112})
        listing, _ = Wishlist.objects.get_or_create(owner=user)
        for title, author, color in [("Una habitación propia", "Virginia Woolf", "blue"), ("La biblioteca de la medianoche", "Matt Haig", "gold")]:
            WishItem.objects.get_or_create(wishlist=listing, title=title, defaults={"author": author, "color": color})
        self.stdout.write(self.style.SUCCESS("Biblioteca y lista de ejemplo preparadas. No se ha publicado ningún contenido."))
