"""Run inside the PythonAnywhere ASGI worker; keep code, venv and data separate."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import time
import venv
import zipfile


def main():
    if not os.environ.get('DOMAIN_SOCKET'):
        raise RuntimeError('This entry point requires the PythonAnywhere ASGI DOMAIN_SOCKET')
    os.umask(0o077)
    home = Path(__file__).resolve().parent
    settings_path = home / 'taphoa360-settings.json'
    settings_path.chmod(0o600)
    settings = json.loads(settings_path.read_text())
    code = home / 'taphoa360-app'
    data = home / 'taphoa360-data'
    environment = home / 'taphoa360-venv'
    code.mkdir(exist_ok=True)
    data.mkdir(exist_ok=True)
    with zipfile.ZipFile(home / 'taphoa360-release.zip') as archive:
        manifest = json.loads(archive.read('MANIFEST.sha256.json'))
        for name, digest in manifest.items():
            relative = PurePosixPath(name)
            if relative.is_absolute() or '..' in relative.parts or '\\' in name:
                raise RuntimeError('Invalid release path')
            contents = archive.read(name)
            if hashlib.sha256(contents).hexdigest() != digest:
                raise RuntimeError('Release integrity check failed: ' + name)
            target = code.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(contents)
    python = environment / 'bin' / 'python'
    if not python.exists():
        venv.create(environment, with_pip=True)
    lock = code / 'requirements.lock.txt'
    lock_hash = hashlib.sha256(lock.read_bytes()).hexdigest()
    installed = environment / '.taphoa-requirements'
    if not installed.exists() or installed.read_text() != lock_hash:
        # Free ASGI workers have no outbound network. Install verified Linux wheels
        # uploaded by the deployment client, never contact package indexes here.
        wheel_dir = home / 'taphoa360-wheels'
        wheel_dir.mkdir(exist_ok=True)
        with zipfile.ZipFile(home / 'taphoa360-wheels.zip') as wheel_archive:
            for name in wheel_archive.namelist():
                if PurePosixPath(name).name != name or not name.endswith('.whl'):
                    raise RuntimeError('Invalid dependency archive')
                (wheel_dir / name).write_bytes(wheel_archive.read(name))
        subprocess.run([str(python), '-m', 'pip', 'install', '--no-cache-dir',
                        '--no-compile', '--disable-pip-version-check', '--no-index',
                        '--find-links', str(wheel_dir), '-r', str(lock)], check=True)
        installed.write_text(lock_hash)
    os.environ.update({
        'APP_ENV': 'production', 'RELOAD': 'false', 'SEED_DEMO': 'false',
        'COOKIE_SECURE': 'true', 'ENABLE_DOCS': 'false', 'DB_TYPE': 'sqlite',
        'SQLITE_PATH': str(data / 'taphoa360.db'), 'SQLITE_JOURNAL_MODE': 'DELETE',
        'ALLOWED_HOSTS': settings['domain'] + ',localhost,127.0.0.1',
        'PUBLIC_ORIGIN': 'https://' + settings['domain'],
        'SETUP_TOKEN': settings['setup_token'], 'CONTAINER_RUNTIME': 'false',
        'FORWARDED_ALLOW_IPS': '*', 'TZ': 'Asia/Ho_Chi_Minh',
        'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONUNBUFFERED': '1',
    })
    if hasattr(time, 'tzset'):
        time.tzset()
    os.chdir(code)
    print('Starting Taphoa360 on PythonAnywhere; persistent data directory is ready.', flush=True)
    os.execv(str(python), [str(python), str(code / 'serve.py')])


if __name__ == '__main__':
    main()
