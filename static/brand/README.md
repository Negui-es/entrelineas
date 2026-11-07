# Entrelíneas · Marca elegida

Todos los SVG contienen trazados reales: no incluyen imágenes incrustadas,
fuentes, scripts ni recursos externos. Fondo transparente.

- `entrelineas-symbol.svg`: símbolo de libro y comillas.
- `entrelineas-wordmark.svg`: nombre con el acento violeta.
- `entrelineas-logo.svg`: composición horizontal completa.
- Sufijo `-mono.svg`: versión de una tinta oscura, adaptable mediante `color`
  cuando se inserta el SVG en línea.
- Sufijo `-white.svg`: versión blanca para fondos oscuros.

Los archivos en color se adaptan al modo oscuro del sistema. En la web se
utilizan los mismos trazados en línea y los colores de la interfaz.
El favicon está en `static/favicon.svg`.

Se ha reconstruido el símbolo y el acento con curvas Bézier. El nombre se ha
vectorizado y suavizado a partir de la propuesta 05 aprobada. Para regenerar:
`python scripts/build_brand.py` (necesita Pillow y la propuesta PNG original).
Después: `python scripts/build_error_pages.py` y
`python manage.py collectstatic --noinput`.
