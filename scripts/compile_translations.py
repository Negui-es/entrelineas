"""Build standard Django PO/MO catalogues without system GNU gettext (Windows)."""
import ast
import json
from pathlib import Path
import re
import struct

ROOT = Path(__file__).resolve().parent.parent
LANGS = ("en", "de", "fr", "it")


def source_messages():
    messages = set()
    for folder in ("library", "accounts", "entrelineas"):
        for path in (ROOT / folder).rglob("*.py"):
            if "migrations" in path.parts or path.name.startswith(("test", "legacy_")):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"_", "gettext", "gettext_lazy"}:
                    if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                        messages.add(node.args[0].value)
    for path in (ROOT / "templates").rglob("*"):
        if path.suffix not in {".html", ".txt"}:
            continue
        source = path.read_text(encoding="utf-8")
        for match in re.finditer(r'{%\s*translate\s+("(?:[^"\\]|\\.)*"|\x27(?:[^\x27\\]|\\.)*\x27)', source):
            messages.add(ast.literal_eval(match[1]))
        from django.utils.translation.template import templatize
        for match in re.finditer(r"\bgettext\((u?'(?:\\.|[^'\\])*')", templatize(source)):
            messages.add(ast.literal_eval(match[1]))
    for path in (ROOT / "static").glob("*.js"):
        for match in re.finditer(r'gettext\(("(?:[^"\\]|\\.)*")\)', path.read_text(encoding="utf-8")):
            messages.add(json.loads(match[1]))
    # The pool stays untranslated until selected, independent of import language.
    tree = ast.parse((ROOT / "entrelineas/errors.py").read_text(encoding="utf-8"))
    pool = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "MESSAGES" for t in n.targets))
    messages.update(text for pairs in pool.values() for pair in pairs for text in pair)
    return messages


def write_mo(path, messages):
    # GNU MO: sorted original/translation tables followed by UTF-8 string pools.
    pairs = sorted((key.encode("utf-8"), value.encode("utf-8")) for key, value in messages.items())
    count = len(pairs)
    originals = b"".join(key + b"\0" for key, value in pairs)
    translations = b"".join(value + b"\0" for key, value in pairs)
    start = 28 + 16 * count
    offset = start
    table = []
    for key, value in pairs:
        table.append((len(key), offset)); offset += len(key) + 1
    offset = start + len(originals)
    for key, value in pairs:
        table.append((len(value), offset)); offset += len(value) + 1
    path.write_bytes(struct.pack('<7I', 0x950412de, 0, count, 28, 28 + count * 8, 0, 0) +
                     b"".join(struct.pack('<2I', *entry) for entry in table) + originals + translations)


PLURALS = {
    "%(count)s reseña": ("%(count)s reseñas", [
        ("%(count)s review", "%(count)s reviews"), ("%(count)s Rezension", "%(count)s Rezensionen"),
        ("%(count)s avis", "%(count)s avis"), ("%(count)s recensione", "%(count)s recensioni")]),
    "%(count)s resultado": ("%(count)s resultados", [
        ("%(count)s result", "%(count)s results"), ("%(count)s Ergebnis", "%(count)s Ergebnisse"),
        ("%(count)s résultat", "%(count)s résultats"), ("%(count)s risultato", "%(count)s risultati")]),
}


def main():
    data = json.loads((ROOT / "locale/messages.json").read_text(encoding="utf-8"))
    missing = source_messages() - data.keys()
    if missing:
        raise SystemExit("Missing translations:\n" + "\n".join(sorted(missing)))
    for lang in ("es", *LANGS):
        index = LANGS.index(lang) if lang != "es" else None
        plural_rule = "(n > 1)" if lang == "fr" else "(n != 1)"
        header = f"Language: {lang}\nContent-Type: text/plain; charset=UTF-8\nContent-Transfer-Encoding: 8bit\nPlural-Forms: nplurals=2; plural={plural_rule};\n"
        messages = {"": header}
        quote = lambda text: json.dumps(text, ensure_ascii=False)
        po = ["# Entrelíneas interface translations. Generated from locale/messages.json.", 'msgid ""', "msgstr " + quote(header), ""]
        for key, values in sorted(data.items()):
            if len(values) != 4 or not all(isinstance(value, str) and value for value in values):
                raise SystemExit("Invalid translations: " + key)
            value = key if index is None else values[index]
            if set(re.findall(r'%\([^)]+\)\w', key)) != set(re.findall(r'%\([^)]+\)\w', value)):
                raise SystemExit("Mismatched placeholders: " + key + " / " + lang)
            messages[key] = value
            po.extend(["msgid " + quote(key), "msgstr " + quote(value), ""])
        for singular, (plural, translations) in PLURALS.items():
            values = (singular, plural) if index is None else translations[index]
            messages[singular + "\0" + plural] = "\0".join(values)
            po.extend(["msgid " + quote(singular), "msgid_plural " + quote(plural),
                       "msgstr[0] " + quote(values[0]), "msgstr[1] " + quote(values[1]), ""])
        directory = ROOT / "locale" / lang / "LC_MESSAGES"
        directory.mkdir(parents=True, exist_ok=True)
        for domain in ("django", "djangojs"):
            (directory / (domain + ".po")).write_text("\n".join(po), encoding="utf-8")
            write_mo(directory / (domain + ".mo"), messages)
    print(f"Compiled {len(data)} messages in 5 languages.")


if __name__ == "__main__":
    main()
