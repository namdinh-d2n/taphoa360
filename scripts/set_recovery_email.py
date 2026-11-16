"""Link an existing owner's recovery email from the machine hosting the store."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--username', required=True)
    parser.add_argument('--email', required=True)
    args = parser.parse_args()
    from fastapi import HTTPException
    from retail.database import migrate, one, reading, transaction
    from retail.password_recovery import normalize_email, ensure_email_available, invalidate_resets
    from retail.reporting import make_backup
    from retail.common import audit
    try:
        email = normalize_email(args.email)
        if not email:
            parser.error('Email must not be empty.')
        migrate()
        with reading() as conn:
            account = one(conn, "SELECT * FROM users WHERE username=? AND role='owner' AND active=1", (args.username.lower(),))
            if not account:
                parser.error('Active owner account not found.')
            ensure_email_available(conn, email, account['id'])
        make_backup(None, 'before-recovery-email')
        with transaction() as conn:
            ensure_email_available(conn, email, account['id'])
            conn.execute('UPDATE users SET email=? WHERE id=?', (email, account['id']))
            invalidate_resets(conn, account['id'])
            audit(conn, account, 'LINK_RECOVERY_EMAIL_LOCAL', account['id'], {})
        print('Recovery email linked for owner: ' + account['username'])
    except HTTPException as error:
        parser.error(str(error.detail))


if __name__ == '__main__':
    main()
