"""Bounded persistent cache for a fixed, public DSS survey and pinned Aladin JS."""
import sqlite3
import threading
import time
import urllib.request
from runtime_paths import BASE

FILE = BASE / 'data' / 'web-cache.sqlite'
LIMIT = 2 * 1024**3
MAX_OBJECT = 32 * 1024**2
locks = [threading.Lock() for _ in range(32)]

def connect():
    FILE.parent.mkdir(parents=True, exist_ok=True)
    c=sqlite3.connect(FILE, timeout=30)
    c.execute('CREATE TABLE IF NOT EXISTS cache (url TEXT PRIMARY KEY, body BLOB, mime TEXT, used REAL)')
    return c

def fetch(url):
    with locks[hash(url)%len(locks)]:
        with connect() as c:
            row=c.execute('SELECT body,mime FROM cache WHERE url=?',(url,)).fetchone()
            if row:
                c.execute('UPDATE cache SET used=? WHERE url=?',(time.time(),url))
        c.close()
        if row:return row[0],row[1],True
        with urllib.request.urlopen(url,timeout=12) as response:
            body=response.read(MAX_OBJECT+1)
            mime=response.headers.get_content_type()
        if len(body)>MAX_OBJECT:raise ValueError('Cache object exceeds 32 MiB')
        if not body or mime=='text/html':raise ValueError('Unexpected empty/HTML survey response')
        with connect() as c:
            c.execute('INSERT OR REPLACE INTO cache VALUES (?,?,?,?)',(url,body,mime,time.time()))
            total=c.execute('SELECT COALESCE(SUM(length(body)),0) FROM cache').fetchone()[0]
            while total>LIMIT:
                old,size=c.execute('SELECT url,length(body) FROM cache ORDER BY used LIMIT 1').fetchone()
                c.execute('DELETE FROM cache WHERE url=?',(old,));total-=size
        c.close()
        return body,mime,False

def stats():
    with connect() as c:
        count,size=c.execute('SELECT count(*),COALESCE(SUM(length(body)),0) FROM cache').fetchone()
    c.close()
    return dict(objects=count,bytes=size,limit_bytes=LIMIT,offline_note='Only previously visited tiles are cached; not a full-sky offline survey.')
