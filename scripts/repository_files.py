"""Code boundary used by the audit and publication tools."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {'.gitignore', '.dockerignore', '.env.example', '.env.production.example',
              'compose.yaml', 'Dockerfile', 'manage.py', 'requirements.txt', 'servidor.py',
              'iniciar.ps1', 'iniciar-publicado.ps1', 'README.md', 'LICENSE'}
SUFFIXES = {'entrelineas': {'.py'}, 'accounts': {'.py'}, 'library': {'.py'},
            'templates': {'.html', '.txt', '.js'}, 'locale': {'.po', '.json'},
            'static': {'.css', '.js', '.json', '.svg', '.png', '.ico', '.md', '.txt'},
            'scripts': {'.py', '.cjs', '.mjs'}, 'deploy': {'.sh', '.js', '.html', '.md'}}


def repository_files():
    for name in sorted(ROOT_FILES):
        path = ROOT / name
        if path.is_file():
            yield path
    for directory, suffixes in SUFFIXES.items():
        for path in sorted((ROOT / directory).rglob('*')):
            if path.is_file() and path.suffix in suffixes and '__pycache__' not in path.parts:
                if path.is_symlink() or not path.resolve().is_relative_to(ROOT):
                    raise ValueError('Unexpected source link')
                yield path
