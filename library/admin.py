from django.contrib import admin
from .models import Book, ReadingNote, Review, Wishlist, WishItem, Work, Edition, CatalogSource

@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    list_display = ["title", "author", "owner", "status"]
    search_fields = ["title", "author"]
    list_filter = ["status"]

admin.site.register([Review, ReadingNote, Wishlist, WishItem])
admin.site.register([Work, Edition, CatalogSource])
