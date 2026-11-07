"""Production configuration and first-run behavior on disposable databases."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class ProductionTests(unittest.TestCase):
    def run_production(self, code, **overrides):
        with tempfile.TemporaryDirectory(prefix='taphoa-production-') as folder:
            env = {**os.environ, 'APP_ENV': 'production', 'DB_TYPE': 'sqlite',
                   'SEED_DEMO': 'false', 'RELOAD': 'false', 'COOKIE_SECURE': 'true',
                   'ENABLE_DOCS': 'false', 'ALLOWED_HOSTS': 'shop.example,127.0.0.1,healthcheck.railway.app',
                   'SETUP_TOKEN': 'test-only-setup-token-' + 'x' * 32,
                   'SQLITE_PATH': str(Path(folder) / 'store.db'), **overrides}
            return subprocess.run([sys.executable, '-c', code], env=env, capture_output=True,
                                  text=True, encoding='utf-8', timeout=30)

    def test_clean_setup_token_secure_cookie_hosts_and_restart(self):
        result = self.run_production('''
import config
from fastapi.testclient import TestClient
from app import app
from retail.database import reading
with TestClient(app, base_url='https://shop.example') as client:
    assert client.get('/health/ready').status_code == 200
    assert client.get('/docs').status_code == 404
    assert client.get('/openapi.json').status_code == 404
    assert client.get('/health/ready', headers={'Host':'evil.example'}).status_code == 400
    assert client.get('/health/ready', headers={'Host':'healthcheck.railway.app'}).status_code == 200
    with reading() as conn:
        for table in ['products','orders','employees','attendance','payroll','shift_schedule','stock_batches']:
            assert conn.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] == 0, table
    data = {'username':'owner','name':'Owner','password':'test-password-123'}
    assert client.post('/api/setup', json=data).status_code == 403
    data['setup_token'] = config.SETUP_TOKEN
    assert client.post('/api/setup', json=data).status_code == 200
    response = client.post('/api/login', json=data)
    assert response.status_code == 200
    assert 'Secure' in response.headers['set-cookie'] and 'HttpOnly' in response.headers['set-cookie']
    assert client.get('/owner').status_code == 200
    assert client.post('/api/setup', json=data).status_code == 409
    headers = {'X-CSRF-Token': response.json()['csrf']}
    response = client.post('/api/v1/products', json={'product_name':'Real item','sku':'REAL','price':12000,'unit':'piece','zone_code':'A1'}, headers=headers)
    assert response.status_code == 200, response.text
with TestClient(app, base_url='https://shop.example') as client:
    assert client.get('/api/setup-status').json() == {'required':False}
    with reading() as conn:
        assert conn.execute("SELECT COUNT(*) FROM products WHERE sku='REAL'").fetchone()[0] == 1
        assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_first_run_requires_secret(self):
        result = self.run_production('from fastapi.testclient import TestClient\nfrom app import app\nwith TestClient(app): pass', SETUP_TOKEN='')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('SETUP_TOKEN', result.stderr)

    def test_canonical_https_origin_behind_http_proxy(self):
        result = self.run_production('''
from fastapi.testclient import TestClient
from app import app
with TestClient(app, base_url='http://shop.example') as client:
    for origin in ['http://shop.example','https://evil.example']:
        response = client.post('/api/setup', json={}, headers={'Origin':origin})
        assert response.status_code == 403
        assert 'Nguồn' in response.json()['detail']
    response = client.post('/api/setup', json={}, headers={'Origin':'https://shop.example'})
    assert response.status_code == 403
    assert 'thiết lập' in response.json()['detail']
''', PUBLIC_ORIGIN='https://shop.example')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_shared_disk_journal_survives_restart(self):
        result = self.run_production('''
from fastapi.testclient import TestClient
from app import app
from retail.database import reading
for _ in range(2):
    with TestClient(app, base_url='https://shop.example') as client:
        assert client.get('/health/ready').status_code == 200
        with reading() as conn:
            assert conn.execute('PRAGMA journal_mode').fetchone()[0] == 'delete'
            assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
''', SQLITE_JOURNAL_MODE='DELETE')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_pythonanywhere_uses_domain_socket(self):
        result = self.run_production('''
import os
from unittest.mock import patch
import serve
with patch.dict(os.environ, {'DOMAIN_SOCKET':'/var/sockets/shop/app.sock','CONTAINER_RUNTIME':'false'}):
    with patch('serve.uvicorn.run') as run:
        serve.main()
        assert run.call_args.kwargs['uds'] == '/var/sockets/shop/app.sock'
        assert 'port' not in run.call_args.kwargs
        assert run.call_args.kwargs['workers'] == 1
''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_unsafe_production_options_fail_closed(self):
        for options in [{'RELOAD': 'true'}, {'SEED_DEMO': 'true'}, {'COOKIE_SECURE': 'false'}, {'ALLOWED_HOSTS': '*'}]:
            result = self.run_production('import config', **options)
            self.assertNotEqual(result.returncode, 0, options)


if __name__ == '__main__':
    unittest.main()
