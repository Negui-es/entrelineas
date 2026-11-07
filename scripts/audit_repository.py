"""Audit source without printing credentials or private data values."""
import re
import subprocess
import sys
from repository_files import ROOT, repository_files

PATTERNS = {
    'token de servicio': re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,})'),
    'clave privada': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'hash de contraseÃ±a real': re.compile(r'pbkdf2_sha256\$\d+\$'),
    'ruta personal': re.compile(r'[A-Za-z]:[/\\]Users[/\\](?!private[/\\]|Public[/\\])[^/\\\s]+', re.I),
    'configuraciÃ³n de la instalaciÃ³n original': re.compile(r'canela\.negui\.es|192\.168\.1\.'),
}


def main():
    files = list(repository_files())
    allowed = {path.relative_to(ROOT).as_posix() for path in files}
    tracked = subprocess.run(['git', '-C', str(ROOT), 'ls-files', '-z'], capture_output=True)
    problems = []
    if tracked.returncode == 0:
        for name in tracked.stdout.decode().split('\0'):
            if name and name not in allowed:
                problems.append((name, 'archivo fuera de la lista de cÃ³digo publicable'))
    for path in files:
        relative = path.relative_to(ROOT).as_posix()
        if path.suffix in {'.png', '.ico'}:
            continue
        text = path.read_text(encoding='utf-8-sig')
        for label, pattern in PATTERNS.items():
            if pattern.search(text):
                problems.append((relative, label))
    for relative, label in problems:
        print(f'REVISAR {relative}: {label}')
    if problems:
        return 1
    print(f'AuditorÃ­a correcta: {len(files)} archivos de cÃ³digo, interfaz y documentaciÃ³n.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
