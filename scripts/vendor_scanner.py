"""Vendor the pinned ZXing browser bundle from npm, checking its registry integrity."""
import base64
import hashlib
import io
import json
import tarfile
from pathlib import Path
from urllib.request import urlopen

VERSION = "0.2.1"
root = Path(__file__).resolve().parent.parent
with urlopen(f"https://registry.npmjs.org/@zxing/browser/{VERSION}", timeout=20) as response:
    metadata = json.load(response)
with urlopen(metadata["dist"]["tarball"], timeout=30) as response:
    archive = response.read(8_000_000)
expected = metadata["dist"]["integrity"]
actual = "sha512-" + base64.b64encode(hashlib.sha512(archive).digest()).decode()
if actual != expected:
    raise RuntimeError("La integridad del paquete no coincide con el registro npm.")
destination = root / "static" / "vendor"
destination.mkdir(parents=True, exist_ok=True)
with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as package:
    for source, target in [
        ("package/umd/zxing-browser.min.js", "zxing-browser.min.js"),
        ("package/LICENSE", "ZXING-LICENSE.txt"),
    ]:
        entry = package.extractfile(source)
        if entry is None:
            raise RuntimeError(f"Archivo ausente: {source}")
        (destination / target).write_bytes(entry.read())
(destination / "zxing-version.json").write_text(json.dumps({
    "package": "@zxing/browser", "version": VERSION, "integrity": expected,
    "source": metadata["dist"]["tarball"],
}, indent=2), encoding="utf-8")
print(f"ZXing browser {VERSION}: bundle y licencia guardados; integridad SHA-512 verificada.")
