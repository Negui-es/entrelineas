# Respaldo de Entrelíneas en Cloudflare Workers

Archivo listo para pegar: `cloudflare-worker.js`. Incluye el HTML, CSS y JavaScript de la página de caída; no necesita archivos externos, secretos ni conexiones con servicios adicionales.

## Desde el panel de Cloudflare

1. Crear un Worker llamado, por ejemplo, `entrelineas-respaldo` en Workers & Pages.
2. Abrir el editor de código, sustituir el ejemplo por **todo** el contenido de `cloudflare-worker.js` y desplegarlo.
3. En la configuración de dominios y rutas del Worker, añadir una **Route / Ruta**, seleccionando la zona `negui.es` y el patrón `entrelineas.negui.es/*`.
4. Conservar el registro DNS proxied de ese subdominio que ya apunta al túnel. No sustituirlo y no asociar el Worker mediante Custom Domain / Dominio personalizado: el origen sigue siendo el servidor detrás del túnel.
5. Con el servidor encendido, comprobar acceso, estilos y un formulario. Después, detener solamente Entrelíneas de forma controlada y cargar el dominio: debe aparecer la página 503. Encender el servidor y comprobar que la aplicación vuelve sin modificar el Worker.

Si se habilita temporalmente un dominio workers.dev, este sirve la página de respaldo como muestra sin intentar conectarse al origen. El patrón de ruta es el que activa el comportamiento real para el dominio de la app.

## Con Wrangler (opcional)

`wrangler.jsonc` ya contiene la ruta y el archivo principal. Desde esta carpeta, usando una instalación de Wrangler autenticada con acceso a la zona:

```sh
wrangler deploy
```

No se ha ejecutado el despliegue ni se ha modificado la cuenta de Cloudflare desde este proyecto.

## Comportamiento

- Reenvía la petición original, conservando método, cuerpo y cookies. Devuelve los redireccionamientos al navegador sin seguirlos desde el Worker.
- Deja pasar las respuestas de Django, incluidas sus páginas 404/500 y el estado 503 cuando fallan los catálogos.
- Ante una excepción de conexión o los estados de origen/pasarela 502, 504, 520–526 o 530, devuelve una respuesta 503 independiente.
- Devuelve HTML a las navegaciones del navegador y JSON a las peticiones que no solicitan HTML. Las peticiones HEAD no reciben cuerpo.
- No cachea la página de respaldo, no reutiliza contenido privado y no hace reintentos automáticos de peticiones o escrituras. Si se interrumpe una escritura, advierte que debe comprobarse su resultado antes de repetirla.
- La página contiene seis mensajes y funciona también sin JavaScript, con un texto fijo de reserva. Con JavaScript y sessionStorage evita repetir inmediatamente la misma variante.
- Incluye una política CSP con hashes de los estilos y script incluidos. Si se edita directamente el HTML, regenerar también los hashes; es preferible usar el generador.
- No impone un plazo adicional de espera al origen: la página aparece cuando la conexión falla o Cloudflare responde con uno de los estados anteriores. No interrumpe consultas lentas por su cuenta.

Este respaldo funciona cuando el proceso o el ordenador de origen están apagados y Cloudflare sigue siendo accesible. No resuelve bloqueos o incidencias que impidan al visitante llegar al propio Cloudflare, ni errores producidos antes de que el Worker pueda ejecutarse.

## Actualizar el diseño o los mensajes

Desde la raíz del proyecto:

```powershell
.\.venv\Scripts\python.exe scripts/build_error_pages.py
```

Se regeneran `deploy/offline.html` y `deploy/cloudflare-worker.js`. La lógica editable está en `cloudflare-worker.template.js`; después de regenerar hay que volver a desplegar el archivo generado.

Pruebas locales, con Node.js disponible:

```sh
node --test scripts/test_cloudflare_worker.mjs
```

Las diez pruebas verifican paso intacto de respuestas y cookies, fallos del túnel, confidencialidad de errores, envíos POST sin repetición, formato JSON, HEAD, hashes CSP y aislamiento de la vista previa. La ejecución real en Cloudflare se debe comprobar después del despliegue.

Referencia oficial sobre rutas y paso al origen: https://developers.cloudflare.com/workers/configuration/routing/routes/


## Idiomas

El Worker incluye las páginas en español, inglés, alemán, francés e italiano. Un prefijo `/es/`, `/en/`, `/de/`, `/fr/` o `/it/` tiene prioridad; sin él se interpreta `Accept-Language`, con español como reserva. Los seis mensajes aleatorios y los enlaces de vuelta están localizados. Cada página tiene hashes CSP propios. Los cambios requieren volver a desplegar `cloudflare-worker.js`.
