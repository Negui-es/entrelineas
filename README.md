# Entrelíneas

Entrelíneas es una biblioteca personal centrada en las reseñas y las notas de lectura. Permite organizar libros, seguir el progreso de lectura, recordar qué te gustó de cada obra y mantener una lista de deseos. Cada cuenta conserva sus lecturas y opiniones en su espacio privado.

La aplicación utiliza Django 5.2 LTS, plantillas y CSS propio. El despliegue con Docker incluye PostgreSQL. Para desarrollar en local también puede utilizar SQLite.

## Funciones

- Biblioteca con estados de lectura, páginas, fechas, ISBN y portadas.
- Reseñas con estrellas, borradores, favoritos, etiquetas y avisos de spoilers.
- Notas de lectura asociadas a un libro y a una página opcional.
- Resumen de lecturas, actividad mensual y estadísticas anuales.
- Lista de deseos con prioridad, ediciones preferidas y un enlace secreto revocable para compartirla.
- Importación y exportación CSV, importación de Goodreads y conservación de los datos personales al enlazar ediciones del catálogo.
- Búsqueda bibliográfica en proveedores externos y escáner de ISBN mediante cámara o imagen.
- Interfaz en español, inglés, alemán, francés e italiano, con temas claro y oscuro.
- Instalación como aplicación web en móvil y pantalla de desconexión sin almacenar la biblioteca privada en el navegador.

El catálogo de obras y ediciones puede compartirse dentro de una instalación. Las lecturas, las reseñas y las notas pertenecen a cada cuenta. El repositorio contiene código, migraciones, pruebas y recursos de interfaz. Las cuentas, las portadas subidas, las bases de datos, los registros y los secretos se conservan fuera de Git.

## Instalación con Docker

Necesitas Git, Docker y Docker Compose. Clona el repositorio y prepara la configuración.

```sh
git clone https://github.com/Negui-es/entrelineas.git
cd entrelineas
cp .env.example .env
```

En PowerShell también puedes usar `Copy-Item .env.example .env`. Asigna valores aleatorios distintos a `SECRET_KEY` y `POSTGRES_PASSWORD`. La clave de Django debe tener al menos 50 caracteres. Para generar cada valor puedes utilizar Python.

```sh
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Utiliza una contraseña de PostgreSQL segura para una URL, por ejemplo el valor que genera la orden anterior, porque Compose la incorpora a `DATABASE_URL`. El archivo de ejemplo utiliza HTTP local y correo mostrado en los registros del servicio.

```sh
docker compose up --build -d
docker compose ps
```

Abre [http://127.0.0.1:18743](http://127.0.0.1:18743). El arranque aplica las migraciones y prepara la caché compartida de autenticación.

## Primera cuenta y correo

Las altas están cerradas por defecto. Para crear tu primera cuenta, establece `REGISTRATION_OPEN=true`, recrea el servicio con `docker compose up -d` y utiliza el formulario de registro. Debes verificar la dirección antes de acceder a tu biblioteca.

En desarrollo, con `EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend`, el enlace de verificación aparece en los registros.

```sh
docker compose logs --tail=100 web
```

Abre tu enlace de verificación y confirma la dirección. Después puedes cerrar las altas con `REGISTRATION_OPEN=false` y `docker compose up -d`.

Para enviar verificaciones y recuperaciones por correo real, configura SMTP. El ejemplo de producción está en `.env.production.example`. Revisa `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `EMAIL_USE_SSL` y `DEFAULT_FROM_EMAIL` según tu proveedor. El backend de archivos guarda los mensajes en el volumen privado de ejecución.

Para administración de confianza puedes crear una cuenta adicional con esta orden.

```sh
docker compose exec web python manage.py createsuperuser
```

El panel está en `/admin/`. La cuenta administradora tiene acceso de mantenimiento a los datos de la instalación. La verificación de correo también se aplica al acceso normal de la biblioteca. Puedes confirmar tu propia dirección mediante el flujo de correo o gestionar su registro de dirección verificada desde el panel.

## Publicar tu instancia

Configura un dominio propio con HTTPS. Por ejemplo, estos valores de `.env` preparan una instalación detrás de un proxy de confianza.

```dotenv
DEBUG=false
ALLOWED_HOSTS=lecturas.example.org,localhost,127.0.0.1
CSRF_TRUSTED_ORIGINS=https://lecturas.example.org
TRUST_PROXY=true
REGISTRATION_OPEN=false
```

La web escucha en el puerto local `18743` del servidor y PostgreSQL permanece en una red interna de Docker. Un proxy o túnel instalado en el servidor puede apuntar a `http://127.0.0.1:18743`, conservando el host y enviando `X-Forwarded-Proto: https`.

El servicio opcional `tunnel` utiliza la red del host y está previsto para un servidor Linux. Puedes configurarlo con tu propio `TUNNEL_TOKEN` y ejecutar `docker compose --profile public up -d`. En Cloudflare, su ruta debe apuntar al puerto local del servidor. Las páginas y el Worker opcional de `deploy/` incluyen ejemplos de una instalación concreta y deben adaptarse a tu dominio antes de utilizarlos.

Comprueba la configuración de producción y el estado de los servicios.

```sh
docker compose exec web python manage.py check --deploy
docker compose ps
```

El escáner por cámara y la instalación en el móvil necesitan HTTPS o un contexto local admitido por el navegador. Las búsquedas externas requieren acceso a Internet desde el servidor. El token de Boktyven es opcional y se configura mediante `BOKTYVEN_API_TOKEN`; las demás fuentes habilitadas pueden utilizarse sin él. Las consultas bibliográficas envían términos de búsqueda a esos proveedores. Las reseñas y las notas no forman parte de esas consultas.

## Persistencia y copias

| Volumen o archivo | Contenido |
| --- | --- |
| `postgres_data` | Cuentas, direcciones verificadas, catálogo, biblioteca, reseñas, notas, deseos y metadatos de importación |
| `book_covers` | Archivos de portadas subidas |
| `runtime` | Correos guardados en archivos y registros rotatorios del catálogo |
| `.env` | Configuración y secretos de la instalación |

Una copia completa necesita la base de datos, las portadas y los secretos. Guarda también el volumen de ejecución si necesitas conservar los mensajes archivados. Protege las copias y conserva una segunda versión en otro almacenamiento.

En un servidor con una consola compatible con `sh`, `sh deploy/backup.sh` crea un respaldo nativo de PostgreSQL en `backups/`. Guarda las portadas por separado. Para restaurar utiliza `pg_restore` contra una base de destino vacía y recupera los archivos en su volumen, manteniendo permisos de escritura para el usuario del contenedor, UID 10001. Conserva el mismo código o una versión compatible con el esquema restaurado.

Para trasladar una instalación SQLite, utiliza una copia coherente de `db.sqlite3`, exporta los modelos con Django, aplica las migraciones en PostgreSQL y carga los datos en una base vacía antes de crear cuentas. Copia `media/` por separado. Cambiar `DATABASE_URL` únicamente cambia la conexión y no realiza esa migración.

## Actualizar y desarrollar

Guarda una copia y revisa las migraciones antes de actualizar.

```sh
git pull --ff-only
docker compose up --build -d
docker compose logs --tail=50 web
```

Los volúmenes se conservan al recrear los contenedores. `docker compose down -v` elimina sus datos. Recuperar una imagen anterior no revierte migraciones de la base de datos.

Para desarrollar sin Docker, crea un entorno con Python 3.12 e instala `requirements.txt`. Copia `.env.example` a `.env`, deja `DEBUG=true` y omite `DATABASE_URL` para utilizar SQLite. Después ejecuta lo siguiente.

```sh
python scripts/compile_translations.py
python manage.py migrate
python manage.py createcachetable
python manage.py runserver 127.0.0.1:18743
```

Las pruebas utilizan datos sintéticos y una base temporal. Puedes ejecutarlas contra PostgreSQL en una instalación de desarrollo.

```sh
docker compose exec -e DEBUG=true web python manage.py test --noinput
python scripts/audit_repository.py
```

Las pruebas de JavaScript utilizan el ejecutor integrado de Node.js y están en `scripts/test_*.cjs`, `scripts/test_*.mjs` y `scripts/tests/`. El frontend está incluido como archivos estáticos y no necesita una compilación con Node para arrancar.

## Licencia

Entrelíneas se distribuye bajo licencia MIT. El escáner utiliza ZXing, cuyo aviso se conserva en `static/vendor/ZXING-LICENSE.txt`. Las demás dependencias mantienen sus propias licencias.
