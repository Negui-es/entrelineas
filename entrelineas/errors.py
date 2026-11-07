"""Error responses independent of authentication, sessions and database queries."""
from random import choice
from django.utils.translation import gettext as _, get_language
from django.http import HttpResponse
from django.template import loader

MESSAGES = {
    404: (
        ("Este capítulo se lo ha comido el perro.", "Y eso que era una edición digital."),
        ("La página se ha fugado con el marcapáginas.", "Llevaban tiempo haciendo planes entre líneas."),
        ("Aquí había una página. O eso dice el narrador.", "Nunca te fíes del todo de un narrador poco fiable."),
        ("Has encontrado el capítulo invisible.", "Una edición tan exclusiva que ni nosotros la tenemos."),
        ("Esta página está en otra estantería.", "La ordenamos por colores y ahora nadie encuentra nada."),
        ("El índice prometía más de lo que podía dar.", "Un clásico de la literatura de enlaces rotos."),
        ("Esta historia tiene una página arrancada.", "Por suerte, todavía sabemos volver al principio."),
        ("Te has salido del mapa de la novela.", "Aquí solo hay dragones y enlaces que no llevan a ninguna parte."),
    ),
    500: (
        ("El narrador ha perdido el hilo.", "Estamos buscando un ovillo entre las notas al pie."),
        ("Se nos ha caído la estantería.", "El suspense estaba bien. Esto ya era demasiado."),
        ("La trama acaba de dar un giro inesperado.", "De los que no estaban ni en el borrador."),
        ("Nuestro servidor está viviendo un drama.", "Le habíamos pedido una comedia ligera."),
        ("La máquina de escribir se ha atascado.", "Creemos que alguien ha metido un tomo de mil páginas."),
        ("El punto y seguido ha decidido ser punto final.", "Estamos negociando una segunda edición."),
        ("El bibliotecario ha invocado un error ancestral.", "La próxima vez leerá las instrucciones antes del conjuro."),
        ("Este giro de guion necesita una revisión.", "Hasta los superventas pasan por corrección de pruebas."),
    ),
    503: (
        ("Volvemos en un capítulo.", "El bibliotecario dijo «solo una página más». Ya sabes cómo acaba eso."),
        ("La biblioteca está entre capítulos.", "Una pausa para cambiar de escenario y poner el té."),
        ("El servidor ha salido a por otro libro.", "Le dijimos que no empezara una trilogía."),
        ("Estamos cambiando la cinta de la máquina.", "La inspiración sigue aquí. La conexión se ha tomado un descanso."),
        ("Hoy la biblioteca abre por la siguiente página.", "Todavía estamos intentando pasar esta."),
        ("La conexión se ha quedado leyendo en el tren.", "Confiamos en que no se salte demasiadas paradas."),
    ),
    "catalog": (
        ("Los catálogos se han ido al club de lectura.", "Les hemos pedido que vuelvan antes del siguiente capítulo."),
        ("La consulta se ha quedado sin marcapáginas.", "Sabíamos por dónde íbamos. Más o menos."),
        ("El mensajero ha perdido la dirección de la biblioteca.", "Y el mapa estaba, cómo no, dentro de otro libro."),
        ("Nuestros catálogos están pasando página.", "Parece que se les han pegado dos."),
        ("La búsqueda ha hecho una pausa dramática.", "Agradecemos el suspense, pero preferíamos los resultados."),
        ("Los libros no se han ido. La conexión, un poco.", "La próxima búsqueda quizá tenga un argumento más convincente."),
    ),
}


def pick_message(kind):
    headline, joke = choice(MESSAGES[kind])
    return {"headline": _(headline), "joke": _(joke)}


def error_context(code, *, retry=False):
    return {"error_code": code, "message": pick_message(code), "retry": retry, "home_url": "/" + (get_language() or "es") + "/", "search_url": "/" + (get_language() or "es") + "/" + _("buscar/"),
            "explanation": {
                404: _("No encontramos esta página. El enlace puede haber cambiado o el contenido no estar disponible para ti."),
                500: _("No hemos podido completar esta petición. Prueba dentro de un momento. Si estabas guardando algo, comprueba el resultado antes de repetirlo."),
                503: _("Entrelíneas no está disponible en este momento. Intenta entrar de nuevo más tarde."),
            }[code]}


def error_response(request, code):
    # Never pass request: RequestContext would run navigation's database queries.
    context = error_context(code, retry=code == 500 and request.method in {"GET", "HEAD"})
    response = HttpResponse(loader.get_template(f"{code}.html").render(context), status=code)
    response["Cache-Control"] = "private, no-store"
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response


def page_not_found(request, exception):
    return error_response(request, 404)


def server_error(request):
    return error_response(request, 500)
