"""Deploy a verified release via the official API, without uploading shop data."""
import argparse
import json
from pathlib import Path
import re
import secrets
import shlex
import subprocess
import sys
import zipfile
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
HOSTS = {'www.pythonanywhere.com', 'eu.pythonanywhere.com'}


class Client:
    def __init__(self, username, token, host):
        if host not in HOSTS or not re.fullmatch(r'[A-Za-z0-9_-]+', username):
            raise ValueError('Invalid PythonAnywhere host or username')
        self.username, self.token, self.host = username, token, host

    def request(self, method, endpoint, data=None, content_type='application/json', version=0):
        if isinstance(data, dict):
            data = json.dumps(data).encode()
        request = Request(f'https://{self.host}/api/v{version}/user/{self.username}/{endpoint}',
                          data=data, method=method, headers={'Authorization': 'Token ' + self.token,
                          'Content-Type': content_type})
        try:
            with urlopen(request, timeout=60) as response:
                body = response.read()
                return json.loads(body) if 'json' in response.headers.get('Content-Type', '') else body
        except HTTPError as exc:
            detail = exc.read().decode(errors='replace').replace(self.token, '[redacted]')
            raise RuntimeError(f'PythonAnywhere HTTP {exc.code}: {detail[:1500]}') from None

    def upload(self, path, contents):
        boundary = 'taphoa-' + secrets.token_hex(16)
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="content"; filename="upload"\r\n'
                'Content-Type: application/octet-stream\r\n\r\n').encode() + contents + f'\r\n--{boundary}--\r\n'.encode()
        return self.request('POST', 'files/path' + quote(path, safe='/'), body,
                            'multipart/form-data; boundary=' + boundary)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--credentials', type=Path, default=ROOT / '.local/pythonanywhere-credentials.json')
    parser.add_argument('--deploy', action='store_true', help='Upload source and create/reload the app; default is inspection only')
    args = parser.parse_args()
    credentials = json.loads(args.credentials.read_text(encoding='utf-8-sig'))
    client = Client(credentials['username'], credentials['api_token'], credentials.get('host', 'www.pythonanywhere.com'))
    if not client.token or client.token.startswith('PASTE_'):
        raise ValueError('An API token is required. Do not put it in source control.')
    websites = client.request('GET', 'websites/', version=1)
    legacy = client.request('GET', 'webapps/')
    versions = client.request('GET', 'default_python3_version/')
    domain = client.username.lower() + ('.eu.pythonanywhere.com' if client.host.startswith('eu.') else '.pythonanywhere.com')
    remote_home = '/home/' + client.username
    command = '/usr/local/bin/python3.11 ' + shlex.quote(remote_home + '/taphoa360_bootstrap.py')
    existing = next((site for site in websites if site['domain_name'] == domain), None)
    if any(site.get('domain_name') == domain for site in legacy):
        raise RuntimeError('The free domain is already occupied by a WSGI website. Existing websites are never removed automatically.')
    if existing and existing.get('webapp', {}).get('command') != command:
        raise RuntimeError('The domain belongs to a different application; deployment stopped to preserve it.')
    print(json.dumps({'domain': domain, 'existing_app': bool(existing), 'python_versions': versions}, ensure_ascii=False))
    if not args.deploy:
        return
    archive = ROOT / 'output/taphoa360-3.1-source.zip'
    if not archive.exists():
        raise RuntimeError('Run scripts/package_release.py first')
    wheel_dir = ROOT / '.local' / 'deploy-wheels'
    subprocess.run([sys.executable, '-m', 'pip', 'download', '-r', str(ROOT / 'requirements.lock.txt'),
                    '--only-binary=:all:', '--platform', 'manylinux2014_x86_64', '--python-version', '311',
                    '--implementation', 'cp', '--abi', 'cp311', '--dest', str(wheel_dir),
                    '--disable-pip-version-check', '--quiet'], check=True)
    wheels_zip = ROOT / '.local/pythonanywhere-wheels.zip'
    with zipfile.ZipFile(wheels_zip, 'w', zipfile.ZIP_DEFLATED) as bundle:
        for wheel in wheel_dir.glob('*.whl'):
            bundle.write(wheel, wheel.name)
    settings_path = ROOT / '.local' / ('pythonanywhere-' + client.username + '-settings.json')
    settings_path.parent.mkdir(exist_ok=True)
    if settings_path.exists():
        settings = json.loads(settings_path.read_text())
        if settings['domain'] != domain:
            raise RuntimeError('Local deployment settings belong to a different domain')
    else:
        if existing:
            settings = json.loads(client.request('GET', 'files/path' + remote_home + '/taphoa360-settings.json'))
        else:
            settings = {'domain': domain, 'setup_token': secrets.token_urlsafe(40)}
        settings_path.write_text(json.dumps(settings, indent=2), encoding='utf-8')
    client.upload(remote_home + '/taphoa360-release.zip', archive.read_bytes())
    client.upload(remote_home + '/taphoa360-wheels.zip', wheels_zip.read_bytes())
    client.upload(remote_home + '/taphoa360_bootstrap.py', (ROOT / 'scripts/pythonanywhere_bootstrap.py').read_bytes())
    client.upload(remote_home + '/taphoa360-settings.json', json.dumps(settings).encode())
    if existing:
        result = client.request('POST', 'websites/' + domain + '/reload/', version=1)
    else:
        result = client.request('POST', 'websites/', {'domain_name': domain, 'enabled': True,
                                'webapp': {'command': command}}, version=1)
    print(json.dumps({'url': 'https://' + domain, 'deployment_submitted': True,
                      'setup_credentials_file': str(settings_path), 'result': result}, default=str))


if __name__ == '__main__':
    main()
