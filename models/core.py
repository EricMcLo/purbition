import os
import sqlite3
from contextlib import contextmanager

try:
    import turso.lib_sync as turso_sync
    import turso_serverless
except Exception:
    turso_sync = None
    turso_serverless = None


# When TURSO_REPLICA_PATH is *also* set, we use a local embedded replica
# (turso.lib_sync.connect_sync) instead of the HTTP-only path. Reads hit a
# local on-disk SQLite file and the replica transparently syncs in the
# background / on connect, so they're blindingly fast for a tiny server
# and a snappy one. The replica is tiny (~25KB) and re-bootstraps on cold
# start. But libSQL's serverless HTTP path is read-only-ish for some ops
# and a regular sqlite3 connection locally is trivial for tests.
TURSO_DATABASE_URL = os.environ.get('TURSO_DATABASE_URL', '')
TURSO_AUTH_TOKEN = os.environ.get('TURSO_AUTH_TOKEN', '')
TURSO_REPLICA_PATH = os.environ.get('TURSO_REPLICA_PATH', '')


def get_db_path():
    return os.environ.get('ADVENTURE_DB_PATH') or 'database.db'


class _DictRow:
    """Dict-like row wrapper for the embedded-replica path.

    The replica path returns plain Python tuples, but the rest of the
    app (Jinja templates, get_all_adventures() callers, etc.) expects
    dict-like access like row['name'] and row.name. This tiny wrapper
    adds both.
    """
    def __init__(self, cols, values):
        self._cols = cols
        self._values = values
        # expose keys
        self._map = dict(zip(cols, values))

    def __getitem__(self, key):
        return self._map[key]

    def __getattr__(self, key):
        if key in self._map:
            return self._map[key]
        raise AttributeError(key)

    def __contains__(self, key):
        return key in self._map

    def keys(self):
        return self._cols

    def __iter__(self):
        return iter(self._map)

    def __repr__(self):
        return repr(self._map)


class _WriteTrackingConnection:
    """Wrap a turso_sync connection so `push()` (slow) only runs after writes.

    libSQL's embedded-replica `push()` is a ~2-3s network round-trip even
    with nothing to send. By tracking dirty state, we call `push()` only when
    writes occurred (INSERT/UPDATE/DELETE/REPLACE/PRAGMA write ops), avoiding
    blocking page reads.
    """
    def __init__(self, conn):
        self._conn = conn
        self.dirty = False

    def execute(self, sql, *args, **kwargs):
        self._mark_dirty(sql)
        return self._conn.execute(sql, *args, **kwargs)

    def executemany(self, sql, *args, **kwargs):
        self._mark_dirty(sql)
        return self._conn.executemany(sql, *args, **kwargs)

    def executescript(self, sql, *args, **kwargs):
        self._mark_dirty(sql)
        return self._conn.executescript(sql, *args, **kwargs)

    def commit(self, *args, **kwargs):
        res = self._conn.commit(*args, **kwargs)
        # Push after commit if we wrote. Some drivers don't have push; ignore.
        if self.dirty:
            try:
                if hasattr(self._conn, 'push'):
                    self._conn.push()
            except Exception:
                pass
            self.dirty = False
        return res

    def rollback(self, *args, **kwargs):
        res = self._conn.rollback(*args, **kwargs)
        # Discard dirty marker on rollback.
        self.dirty = False
        return res

    def close(self, *args, **kwargs):
        res = self._conn.close(*args, **kwargs)
        self.dirty = False
        return res

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def _mark_dirty(self, sql):
        if not sql:
            return
        s = sql.lstrip().lower()
        if s.startswith(('insert', 'update', 'delete', 'replace', 'create', 'drop', 'alter', 'vacuum')):
            self.dirty = True
        # PRAGMA writes are rare; include common ones? PRAGMA foreign_keys ON is read-like;
        # writes like journal_mode affect state — treat as read-only unless obvious write.


def _connect():
    if TURSO_DATABASE_URL and TURSO_REPLICA_PATH:
        # Embedded replica path: local file + sync to remote Turso.
        if turso_sync is None:
            import turso.lib_sync as _t
            conn = _t.connect_sync(
                path=TURSO_REPLICA_PATH,
                remote_url=TURSO_DATABASE_URL,
                auth_token=TURSO_AUTH_TOKEN,
                client_name='adventure-app',
            )
        else:
            conn = turso_sync.connect_sync(
                path=TURSO_REPLICA_PATH,
                remote_url=TURSO_DATABASE_URL,
                auth_token=TURSO_AUTH_TOKEN,
                client_name='adventure-app',
            )
        def _row_factory(cursor, row):
            cols = [d[0] for d in cursor.description]
            return _DictRow(cols, row)
        conn.row_factory = _row_factory
        return _WriteTrackingConnection(conn)
    if TURSO_DATABASE_URL:
        if turso_serverless is None:
            import turso_serverless as _ts
            conn = _ts.connect(TURSO_DATABASE_URL, auth_token=TURSO_AUTH_TOKEN)
        else:
            conn = turso_serverless.connect(TURSO_DATABASE_URL, auth_token=TURSO_AUTH_TOKEN)
        conn.row_factory = lambda cursor, row: row
        return conn
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


@contextmanager
def get_db():
    conn = _connect()
    try:
        # On the embedded-replica path, avoid calling push() on read-only
        # requests. We track whether any write happened; if not dirty, skip
        # the (slow, ~2-3s) remote sync. The route code calls commit() at the
        # end of write transactions, which still triggers push() when dirty.
        if TURSO_REPLICA_PATH and hasattr(conn, 'dirty') and not conn.dirty:
            yield conn
            return
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        # For the non-replica SQLite/turso_serverless paths, close is fine.
        # The WriteTrackingConnection proxies close() too.
        conn.close()


def init_db():
    with get_db() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS adventures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            date TEXT NOT NULL,
            time TEXT,
            location TEXT NOT NULL,
            description TEXT,
            share_id TEXT UNIQUE NOT NULL,
            created_at TEXT NOT NULL,
            vibe TEXT,
            packing_list TEXT,
            carpool INTEGER DEFAULT 0,
            tagline TEXT,
            weather_json TEXT,
            weather_fetched_at TEXT,
            show_weather INTEGER DEFAULT 1,
            end_date TEXT,
            end_time TEXT,
            latitude REAL,
            longitude REAL,
            created_by_attendee_id INTEGER,
            creator_carpool_mode TEXT,
            deleted_at TEXT,
            cost TEXT,
            series_id TEXT,
            recurrence_rule TEXT,
            show_splits INTEGER DEFAULT 0,
            show_gear INTEGER DEFAULT 0,
            cover_image TEXT
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS attendees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            adventure_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            token TEXT NOT NULL,
            driving INTEGER DEFAULT 0,
            seats INTEGER,
            departure_time TEXT,
            departure_location TEXT,
            needs_ride INTEGER DEFAULT 0,
            ride_with_driver_id INTEGER,
            venmo_handle TEXT,
            splits INTEGER DEFAULT 1,
            FOREIGN KEY(adventure_id) REFERENCES adventures(id) ON DELETE CASCADE,
            FOREIGN KEY(ride_with_driver_id) REFERENCES attendees(id) ON DELETE SET NULL,
            UNIQUE(adventure_id, token)
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS cost_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            adventure_id INTEGER NOT NULL,
            label TEXT NOT NULL,
            amount REAL NOT NULL,
            sort_order INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY(adventure_id) REFERENCES adventures(id) ON DELETE CASCADE
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            adventure_id INTEGER NOT NULL,
            paid_by_attendee_id INTEGER,
            label TEXT NOT NULL,
            amount REAL NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(adventure_id) REFERENCES adventures(id) ON DELETE CASCADE,
            FOREIGN KEY(paid_by_attendee_id) REFERENCES attendees(id) ON DELETE CASCADE
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS packing_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            adventure_id INTEGER NOT NULL,
            label TEXT NOT NULL,
            quantity INTEGER DEFAULT 1,
            claimed_by_attendee_id INTEGER,
            created_at TEXT NOT NULL,
            FOREIGN KEY(adventure_id) REFERENCES adventures(id) ON DELETE CASCADE,
            FOREIGN KEY(claimed_by_attendee_id) REFERENCES attendees(id) ON DELETE SET NULL
        )''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_attendees_adventure ON attendees(adventure_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_adventures_deleted_at ON adventures(deleted_at)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_adventures_share_id ON adventures(share_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_cost_items_adventure ON cost_items(adventure_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_expenses_adventure ON expenses(adventure_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_packing_items_adventure ON packing_items(adventure_id)')
        try:
            conn.execute('ALTER TABLE adventures ADD COLUMN series_id TEXT')
        except Exception:
            pass
        try:
            conn.execute('ALTER TABLE adventures ADD COLUMN recurrence_rule TEXT')
        except Exception:
            pass
        try:
            conn.execute('ALTER TABLE adventures ADD COLUMN show_splits INTEGER DEFAULT 0')
        except Exception:
            pass
        try:
            conn.execute('ALTER TABLE adventures ADD COLUMN show_gear INTEGER DEFAULT 0')
        except Exception:
            pass
        try:
            conn.execute('ALTER TABLE adventures ADD COLUMN cover_image TEXT')
        except Exception:
            pass
        try:
            conn.execute('ALTER TABLE packing_items ADD COLUMN quantity INTEGER DEFAULT 1')
        except Exception:
            pass
        conn.execute('CREATE INDEX IF NOT EXISTS idx_attendees_adventure ON attendees(adventure_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_adventures_deleted_at ON adventures(deleted_at)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_adventures_share_id ON adventures(share_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_cost_items_adventure ON cost_items(adventure_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_expenses_adventure ON expenses(adventure_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_packing_items_adventure ON packing_items(adventure_id)')
        try:
            conn.execute('ALTER TABLE adventures ADD COLUMN series_id TEXT')
        except Exception:
            pass
        try:
            conn.execute('ALTER TABLE adventures ADD COLUMN recurrence_rule TEXT')
        except Exception:
            pass
        try:
            conn.execute('ALTER TABLE adventures ADD COLUMN show_splits INTEGER DEFAULT 0')
        except Exception:
            pass
        try:
            conn.execute('ALTER TABLE adventures ADD COLUMN show_gear INTEGER DEFAULT 0')
        except Exception:
            pass
        try:
            conn.execute('ALTER TABLE adventures ADD COLUMN cover_image TEXT')
        except Exception:
            pass
