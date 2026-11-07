"""Build a self-contained outage page for hosting independently of Django."""
import json
import base64
import hashlib
import os
from pathlib import Path
import sys
import re

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "entrelineas.settings")


def standalone(context):
    from django.template.loader import get_template
    html = get_template("errors/page.html").render(context)
    css = (ROOT / "static/errors.css").read_text(encoding="utf-8")
    html = html.replace('<link rel="stylesheet" href="/static/errors.css">', "<style>" + css + "</style>")
    js = (ROOT / "static/error-offline.js").read_text(encoding="utf-8")
    return html.replace('<script src="/static/error-offline.js"></script>', "<script>" + js + "</script>")


def main():
    import django
    django.setup()
    from entrelineas.errors import MESSAGES, error_context
    from django.utils.translation import override, gettext as _
    pages = {}
    def csp_hash(html, tag):
        content = re.search(f"<{tag}>(.*?)</{tag}>", html, re.S).group(1)
        return "'sha256-" + base64.b64encode(hashlib.sha256(content.encode()).digest()).decode() + "'"
    for code in ("es", "en", "de", "fr", "it"):
        with override(code):
            notice = _("Si estabas guardando algo, comprueba el resultado cuando vuelva el servicio antes de repetirlo.")
            context = {**error_context(503), "offline": True, "write_notice": notice,
                       "offline_messages": json.dumps([[_(title), _(joke)] for title, joke in MESSAGES[503]], ensure_ascii=False)}
            html = standalone(context)
            (ROOT / f"deploy/offline-{code}.html").write_text(html, encoding="utf-8")
            if code == "es":
                (ROOT / "deploy/offline.html").write_text(html, encoding="utf-8")
            policy = ("default-src 'none'; style-src " + csp_hash(html, "style") + "; script-src " + csp_hash(html, "script") +
                      "; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
            pages[code] = {"html": html, "csp": policy, "message": context["explanation"], "write_notice": notice}
    template = (ROOT / "deploy/cloudflare-worker.template.js").read_text(encoding="utf-8")
    worker = template.replace("/* GENERATED_PAGES */", json.dumps(pages, ensure_ascii=False, indent=2))
    (ROOT / "deploy/cloudflare-worker.js").write_text(worker, encoding="utf-8")
    print("Five standalone outage pages and the multilingual Worker generated.")



if __name__ == "__main__":
    main()
