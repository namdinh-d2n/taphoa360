"""One-click local launcher; prepares the environment and opens the ready web app."""
import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parent
VENV = ROOT / '.venv'
PYTHON = VENV / 'Scripts' / 'python.exe'


def prepare_environment():
    if sys.version_info < (3, 11):
        raise RuntimeError('Can Python 3.11 tro len de chay he thong.')
    if not PYTHON.is_file():
        print('[1/3] Dang tao moi truong .venv...', flush=True)
        subprocess.run([sys.executable, '-m', 'venv', str(VENV)], check=True)
    lockfile = ROOT / 'requirements.lock.txt'
    requirements = lockfile if lockfile.is_file() else ROOT / 'requirements.txt'
    # Compare installed versions without contacting PyPI on every launch.
    check = '''
import importlib.metadata as metadata
from pathlib import Path
import sys
try:
    for line in Path(sys.argv[1]).read_text(encoding='utf-8-sig').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        name, version = line.split('==', 1)
        if metadata.version(name) != version:
            sys.exit(1)
except (ValueError, metadata.PackageNotFoundError):
    sys.exit(1)
'''
    installed = subprocess.run([str(PYTHON), '-c', check, str(requirements)], capture_output=True)
    if installed.returncode:
        print('[1/3] Dang cai thu vien can thiet (can Internet)...', flush=True)
        subprocess.run([str(PYTHON), '-m', 'pip', 'install', '--disable-pip-version-check', '-r', str(requirements)], check=True)
    else:
        print('[1/3] Moi truong va thu vien da san sang.', flush=True)
    if not (ROOT / '.env').is_file():
        shutil.copyfile(ROOT / '.env.example', ROOT / '.env')
        print('[2/3] Da tao cau hinh .env.', flush=True)
    else:
        print('[2/3] Su dung cau hinh .env hien tai.', flush=True)


def is_ready(base_url):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(base_url + '/api/setup-status', timeout=1) as response:
            data = json.load(response)
            if not isinstance(data, dict) or not isinstance(data.get('required'), bool):
                return False
        with opener.open(base_url + '/openapi.json', timeout=1) as response:
            return json.load(response).get('info', {}).get('title') == 'Tạp hóa 360'
    except (OSError, ValueError, AttributeError, urllib.error.URLError):
        return False


def open_page(url, no_browser):
    print('Mo he thong: ' + url, flush=True)
    if not no_browser:
        try:
            if not webbrowser.open(url):
                print('Chua mo duoc trinh duyet. Hay mo dia chi ben tren.', flush=True)
        except OSError:
            print('Hay tu mo dia chi ben tren bang trinh duyet.', flush=True)


def run_server(no_browser):
    from config import HOST, PORT
    import uvicorn

    if not 1 <= PORT <= 65535:
        raise RuntimeError('PORT trong .env phai nam trong 1-65535.')
    connect_host = '127.0.0.1' if HOST == '0.0.0.0' else '::1' if HOST == '::' else HOST
    url_host = '[' + connect_host + ']' if ':' in connect_host else connect_host
    base_url = f'http://{url_host}:{PORT}'
    login_url = base_url + '/login'
    try:
        with socket.create_connection((connect_host, PORT), timeout=1):
            busy = True
    except OSError:
        busy = False
    if busy:
        for _ in range(5):
            if is_ready(base_url):
                print('[3/3] Tap hoa 360 da chay. Khong khoi dong them server.', flush=True)
                open_page(login_url, no_browser)
                return
            time.sleep(.5)
        raise RuntimeError(f'Cong {PORT} dang duoc su dung, nhung Tap hoa 360 chua san sang. Kiem tra server cu hoac doi PORT trong .env.')

    server = uvicorn.Server(uvicorn.Config('app:app', host=HOST, port=PORT, reload=False))
    def open_when_ready():
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline and not server.should_exit:
            if server.started and is_ready(base_url):
                print('[3/3] He thong da san sang.', flush=True)
                open_page(login_url, no_browser)
                return
            time.sleep(.3)
        if not server.should_exit:
            print('Server chua san sang sau 60 giay. Kiem tra loi trong cua so nay.', flush=True)

    print('[3/3] Dang bat server va database...', flush=True)
    print('Giu cua so nay de he thong hoat dong. Nhan Ctrl+C de tat.', flush=True)
    threading.Thread(target=open_when_ready, daemon=True).start()
    server.run()
    if not server.started:
        raise RuntimeError('Server khong khoi dong duoc. Xem thong bao loi ben tren.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-browser', action='store_true', help='Start without opening a browser')
    args = parser.parse_args()
    os.chdir(ROOT)
    try:
        prepare_environment()
        if Path(sys.prefix).resolve() != VENV.resolve():
            # On the first launch, enter the newly created virtual environment.
            command = [str(PYTHON), str(Path(__file__).resolve())]
            if args.no_browser:
                command.append('--no-browser')
            return subprocess.call(command)
        run_server(args.no_browser)
        return 0
    except KeyboardInterrupt:
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print('[LOI] ' + str(exc), flush=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
