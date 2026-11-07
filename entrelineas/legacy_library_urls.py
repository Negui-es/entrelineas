from django.urls import path
from library import views
from library import catalog_views

urlpatterns = [
    path("buscar/", catalog_views.search, name="catalog_search"),
    path("buscar/ficha/", catalog_views.preview, name="catalog_preview"),
    path("buscar/guardar/", catalog_views.save, name="catalog_save"),
    path("", views.home, name="home"),
    path("resenas/", views.reviews, name="reviews"),
    path("salud/", views.health, name="health"),
    path("biblioteca/", views.library, name="library"),
    path("libros/nuevo/", views.book_edit, name="book_create"),
    path("libros/<int:pk>/", views.book_detail, name="book_detail"),
    path("libros/<int:pk>/editar/", views.book_edit, name="book_edit"),
    path("libros/<int:pk>/eliminar/", views.book_delete, name="book_delete"),
    path("libros/<int:pk>/notas/", views.note_add, name="note_add"),
    path("notas/<int:pk>/eliminar/", views.note_delete, name="note_delete"),
    path("resenas/nueva/", views.review_edit, name="review_create"),
    path("resenas/<int:pk>/editar/", views.review_edit, name="review_edit"),
    path("resenas/<int:pk>/favorita/", views.favorite, name="favorite"),
    path("deseos/", views.wishlist, name="wishlist"),
    path("deseos/nuevo/", views.wish_edit, name="wish_create"),
    path("deseos/<int:pk>/editar/", views.wish_edit, name="wish_edit"),
    path("deseos/<int:pk>/eliminar/", views.wish_delete, name="wish_delete"),
    path("deseos/compartir/", views.wishlist_sharing, name="wishlist_sharing"),
    path("lista/<str:token>/", views.wishlist_shared, name="wishlist_shared"),
]
