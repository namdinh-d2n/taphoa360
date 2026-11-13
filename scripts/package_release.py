"""Create a source-only release; never include shop data or local credentials."""
from pathlib import Path
import hashlib
import json
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    'app.py', 'config.py', 'db.py', 'serve.py', 'start_local.py',
    'BAT_TAPHOA360.bat', 'run.bat', 'requirements.txt',
    'requirements.lock.txt', 'requirements-dev.txt', 'README.md',
    'DEPLOY.md', 'DEPLOY_STATUS.md', 'SYSTEM_OVERVIEW.md', 'QA_REPORT.md', 'Dockerfile',
    '.dockerignore', '.gitignore', '.env.example',
    '.github/workflows/checks.yml', 'scripts/package_release.py',
    'scripts/pythonanywhere_bootstrap.py', 'scripts/deploy_pythonanywhere.py',
]
GLOBS = ['retail/*.py', 'static/*.js', 'static/*.css', 'static/*.svg', 'tests/*.py']
TEMPLATES = ['login', 'register', 'retail', 'receipt']


def main():
    files = [ROOT / name for name in FILES]
    files += [ROOT / 'templates' / (name + '.html') for name in TEMPLATES]
    for pattern in GLOBS:
        files.extend(ROOT.glob(pattern))
    output = ROOT / 'output' / 'taphoa360-3.1-source.zip'
    output.parent.mkdir(exist_ok=True)
    manifest = {}
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(set(files)):
            name = path.relative_to(ROOT).as_posix()
            data = path.read_bytes()
            archive.writestr(name, data)
            manifest[name] = hashlib.sha256(data).hexdigest()
        archive.writestr('MANIFEST.sha256.json', json.dumps(manifest, indent=2))
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        assert not any(name.endswith(('.db', '.pyc')) or name == '.env' for name in archive.namelist())
    print(f'{output} ({len(manifest)} source files, {output.stat().st_size:,} bytes)')


if __name__ == '__main__':
    main()
