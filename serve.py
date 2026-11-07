"""Production entry point: one process, provider PORT, trusted proxy configuration."""
import os
from pathlib import Path

import uvicorn
import config


def main():
    # Container volumes can be initially root-owned. Drop privileges before importing
    # the application; only the mounted data directory is writable by the service.
    if os.name == 'posix' and os.getuid() == 0 and os.getenv('CONTAINER_RUNTIME') == 'true':
        data = Path(config.SQLITE_PATH).parent
        if data.resolve() != Path('/data'):
            raise RuntimeError('Container SQLITE_PATH must be a file directly inside /data')
        data.mkdir(parents=True, exist_ok=True)
        os.chown(data, 10001, 10001)
        for path in data.rglob('*'):
            if not path.is_symlink():
                os.chown(path, 10001, 10001)
        os.setgroups([])
        os.setgid(10001)
        os.setuid(10001)
    os.umask(0o077)
    binding = {'uds': os.environ['DOMAIN_SOCKET']} if os.getenv('DOMAIN_SOCKET') else {'host': config.HOST, 'port': config.PORT}
    uvicorn.run('app:app', **binding, workers=1,
                reload=False, proxy_headers=True,
                forwarded_allow_ips=os.getenv('FORWARDED_ALLOW_IPS', '127.0.0.1'),
                server_header=False, timeout_graceful_shutdown=15)


if __name__ == '__main__':
    main()
