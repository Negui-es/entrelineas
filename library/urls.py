from django.urls import path
from django.utils.translation import gettext_lazy as _
from . import views
from . import catalog_views
from . import manual_views
from .goodreads_views import goodreads_import, library_export

urlpatterns = [
    path(_('biblioteca/mover/'), goodreads_import, name="library_transfer"),
    path(_('biblioteca/importar/'), goodreads_import, name="library_import"),
    path(_('biblioteca/exportar/'), library_export, name="library_export"),
    path(_('biblioteca/importar/goodreads/'), goodreads_import, name="goodreads_import"),
    path(_('buscar/'), catalog_views.search, name="catalog_search"),
    path(_('buscar/ficha/'), catalog_views.preview, name="catalog_preview"),
    path(_('buscar/guardar/'), catalog_views.save, name="catalog_save"),
    path("", views.home, name="home"),
    path(_('resenas/'), views.reviews, name="reviews"),
    path(_('salud/'), views.health, name="health"),
    path(_('biblioteca/'), views.library, name="library"),
    path(_('libros/nuevo/'), manual_views.create, name="book_create"),
    path(_('portadas/<uuid:pk>/'), manual_views.cover, name="edition_cover"),
    path(_('libros/<int:pk>/'), views.book_detail, name="book_detail"),
    path(_('libros/<int:pk>/editar/'), views.book_edit, name="book_edit"),
    path(_('libros/<int:pk>/portada/'), manual_views.add_cover, name="book_cover"),
    path(_('libros/<int:pk>/eliminar/'), views.book_delete, name="book_delete"),
    path(_('libros/<int:pk>/notas/'), views.note_add, name="note_add"),
    path(_('notas/<int:pk>/eliminar/'), views.note_delete, name="note_delete"),
    path(_('resenas/nueva/'), views.review_edit, name="review_create"),
    path(_('resenas/<int:pk>/editar/'), views.review_edit, name="review_edit"),
    path(_('resenas/<int:pk>/favorita/'), views.favorite, name="favorite"),
    path(_('deseos/'), views.wishlist, name="wishlist"),
    path(_('deseos/nuevo/'), views.wish_edit, name="wish_create"),
    path(_('deseos/<int:pk>/editar/'), views.wish_edit, name="wish_edit"),
    path(_('deseos/<int:pk>/eliminar/'), views.wish_delete, name="wish_delete"),
    path(_('deseos/<int:pk>/recibido/'), views.wish_receive, name="wish_receive"),
    path(_('deseos/compartir/'), views.wishlist_sharing, name="wishlist_sharing"),
    path(_('lista/<str:token>/'), views.wishlist_shared, name="wishlist_shared"),
]
