from datetime import datetime
from pathlib import Path
import sqlite3
import config
from .database import reading,transaction,one,add_columns


def migrate_catalog():
    with reading() as conn:
        if one(conn,'SELECT version FROM schema_migrations WHERE version=8'):return
        folder=Path(config.SQLITE_PATH).parent/'backups';folder.mkdir(exist_ok=True)
        backup=sqlite3.connect(folder/('before-v8-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.db'))
        try:conn.backup(backup)
        finally:backup.close()
    with transaction() as conn:
        add_columns(conn,'products',{'brand':"TEXT NOT NULL DEFAULT ''",'catalog_origin':"TEXT NOT NULL DEFAULT 'STORE'",'reference_price':'INTEGER',
                    'reference_source':"TEXT NOT NULL DEFAULT ''",'reference_checked_at':"TEXT NOT NULL DEFAULT ''"})
        add_columns(conn,'suppliers',{'is_sample':'INTEGER NOT NULL DEFAULT 0','note':"TEXT NOT NULL DEFAULT ''"})
        add_columns(conn,'supplier_products',{'is_sample_price':'INTEGER NOT NULL DEFAULT 0'})
        add_columns(conn,'online_orders',{'address_mode':"TEXT NOT NULL DEFAULT 'MANUAL'",'province_code':'INTEGER','ward_code':'INTEGER','address_line':"TEXT NOT NULL DEFAULT ''"})
        conn.execute('INSERT INTO schema_migrations(version) VALUES(8)')
