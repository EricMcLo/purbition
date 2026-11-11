from datetime import date, datetime, timedelta

from .core import get_db
from .ids import generate_share_id


def create_adventure(name, date, time, location, description, vibe=None, packing_list=None, carpool=0, tagline=None, show_weather=1, end_date=None, end_time=None, cost=None, series_id=None, recurrence_rule=None, show_splits=0, show_gear=0):
    share_id = generate_share_id()
    with get_db() as conn:
        conn.execute('''INSERT INTO adventures (name, date, time, location, description, share_id, created_at, vibe, packing_list, carpool, tagline, show_weather, end_date, end_time, cost, series_id, recurrence_rule, show_splits, show_gear)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (name, date, time, location, description, share_id, datetime.utcnow().isoformat(), vibe, packing_list, carpool, tagline, show_weather, end_date, end_time, cost, series_id, recurrence_rule, show_splits, show_gear))
    return share_id
def create_series_occurrences(name, date, time, location, description, vibe, packing_list, carpool, tagline, show_weather, end_date, end_time, cost, series_id, recurrence_rule, count, show_splits=0, show_gear=0):
    """Generate `count` future occurrence rows for a recurring event.

    Each occurrence is a normal adventure row sharing the same series_id and
    details but with its own shifted date (and its own share_id + RSVPs).
    Returns the share_ids of the generated rows.
    """
    first_dt = datetime.strptime(date, '%Y-%m-%d')
    step_days = {'weekly': 7, 'biweekly': 14}[recurrence_rule] if recurrence_rule in ('weekly', 'biweekly') else None
    share_ids = []
    with get_db() as conn:
        for i in range(1, count + 1):
            if step_days:
                occ = first_dt + timedelta(days=step_days * i)
            else:  # monthly: same date-of-month, next month(s); clamp to valid days
                occ = _add_months(first_dt, i)
            occ_date = occ.strftime('%Y-%m-%d')
            occ_end = None
            if end_date:
                end_first = datetime.strptime(end_date, '%Y-%m-%d')
                duration = (end_first - first_dt).days
                occ_end = (occ + timedelta(days=duration)).strftime('%Y-%m-%d')
            sid = generate_share_id()
            conn.execute(
                '''INSERT INTO adventures (name, date, time, location, description, vibe, packing_list, carpool, tagline, show_weather, end_date, end_time, cost, series_id, recurrence_rule, share_id, show_splits, show_gear)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (name, occ_date, time, location, description, vibe, packing_list, carpool, tagline, show_weather, occ_end, end_time, cost, series_id, recurrence_rule, sid, show_splits, show_gear)
            )
            share_ids.append(sid)
        conn.commit()
    return share_ids


def _add_months(dt, n):
    """Return a date `n` months after `dt`, clamping the day to the last valid
    of the target month (e.g. Jan 31 + 1mo -> Feb 28/29)."""
    year = dt.year + (dt.month - 1 + n) // 12
    month = (dt.month - 1 + n) % 12 + 1
    day = min(dt.day, _days_in_month(year, month))
    return datetime(year, month, day)


def _days_in_month(year, month):
    if month == 12:
        return 31
    import calendar
    return calendar.monthrange(year, month)[1]


def get_series(series_id):
    """Return all live occurrences of a series (soonest first)."""
    with get_db() as conn:
        rows = conn.execute(
            'SELECT * FROM adventures WHERE series_id = ? AND deleted_at IS NULL '
            'ORDER BY date ASC, time ASC, created_at ASC',
            (series_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def update_future_series_occurrences(series_id, from_date, name, time, location, description, packing_list=None, carpool=0, tagline=None, show_weather=1, end_date=None, end_time=None, vibe=None, cost=None, show_splits=0, show_gear=0):
    """Apply the same field updates to every future occurrence of a series
    (date >= from_date, including the one that initiated the edit). Date and
    end_date are intentionally NOT overwritten — those are what make each
    occurrence distinct. Single connection = single Turso push on prod.
    Returns the count of rows updated."""
    with get_db() as conn:
        cur = conn.execute(
            '''UPDATE adventures
               SET name = ?, time = ?, location = ?, description = ?, packing_list = ?, carpool = ?, tagline = ?, show_weather = ?, end_time = ?, vibe = ?, cost = ?, show_splits = ?, show_gear = ?,
                   weather_json = NULL, weather_fetched_at = NULL
               WHERE series_id = ? AND deleted_at IS NULL AND date >= ?''',
            (name, time, location, description, packing_list, carpool, tagline, show_weather, end_time, vibe, cost, show_splits, show_gear, series_id, from_date)
        )
        conn.commit()
        return cur.rowcount


def soft_delete_future_series_occurrences(series_id, from_date, deleted_at=None):
    """Soft-delete every future occurrence of a series (date >= from_date,
    including the one that initiated the cancel). Soft-delete keeps the
    24h-undo behavior consistent with the per-adventure delete. Returns the
    count of rows soft-deleted."""
    if deleted_at is None:
        from datetime import datetime as _dt
        deleted_at = _dt.utcnow().isoformat(sep=' ', timespec='seconds')
    with get_db() as conn:
        cur = conn.execute(
            'UPDATE adventures SET deleted_at = ? '
            'WHERE series_id = ? AND deleted_at IS NULL AND date >= ?',
            (deleted_at, series_id, from_date)
        )
        conn.commit()
        return cur.rowcount


def count_future_series_occurrences(series_id, from_date):
    """How many live occurrences a series has from `from_date` forward."""
    with get_db() as conn:
        return conn.execute(
            'SELECT COUNT(*) FROM adventures WHERE series_id = ? AND deleted_at IS NULL AND date >= ?',
            (series_id, from_date)
        ).fetchone()[0]


def update_adventure(adventure_id, name, date, time, location, description, packing_list=None, carpool=0, tagline=None, show_weather=1, end_date=None, end_time=None, vibe=None, cost=None, show_splits=0, show_gear=0, cover_image=None):
    """Update an adventure's fields in place. Share ID and attendees are untouched."""
    with get_db() as conn:
        conn.execute(
            '''UPDATE adventures
               SET name = ?, date = ?, time = ?, location = ?, description = ?, packing_list = ?, carpool = ?, tagline = ?, show_weather = ?, end_date = ?, end_time = ?, vibe = ?, cost = ?, show_splits = ?, show_gear = ?, cover_image = ?
               WHERE id = ?''',
            (name, date, time, location, description, packing_list, carpool, tagline, show_weather, end_date, end_time, vibe, cost, show_splits, show_gear, cover_image, adventure_id)
        )
        conn.commit()


def update_adventure_clearing_weather(adventure_id, name, date, time, location, description, packing_list=None, carpool=0, tagline=None, show_weather=1, end_date=None, end_time=None, vibe=None, cost=None, show_splits=0, show_gear=0, cover_image=None):
    """Update an adventure AND clear its cached weather in a single write.

    The edit route used to call update_adventure() then save_weather(id, None),
    which opened TWO connections — each one triggering its own remote Turso
    `push()` (~2-3s each) on the embedded-replica path. That made "Save Changes"
    take twice as long (~4-6s). Doing both in one `with get_db()` block means a
    single write + single push. Clearing the weather forces a correct refetch on
    the next view after a date/location edit."""
    with get_db() as conn:
        conn.execute(
            '''UPDATE adventures
               SET name = ?, date = ?, time = ?, location = ?, description = ?, packing_list = ?, carpool = ?, tagline = ?, show_weather = ?, end_date = ?, end_time = ?, vibe = ?, cost = ?, show_splits = ?, show_gear = ?, cover_image = ?,
                   weather_json = NULL, weather_fetched_at = NULL
               WHERE id = ?''',
            (name, date, time, location, description, packing_list, carpool, tagline, show_weather, end_date, end_time, vibe, cost, show_splits, show_gear, cover_image, adventure_id)
        )
        conn.commit()


def save_weather(adventure_id, weather_json, fetched_at=None, latitude=None, longitude=None):
    """Store or clear the cached weather payload and optionally the geocoded
    coordinates. None for weather_json clears the cache (e.g. on edit, so a
    location/date typo fix refetches on the next view)."""
    with get_db() as conn:
        if latitude is not None and longitude is not None:
            conn.execute(
                'UPDATE adventures SET weather_json = ?, weather_fetched_at = ?, '
                'latitude = ?, longitude = ? WHERE id = ?',
                (weather_json, fetched_at or datetime.utcnow().isoformat(),
                 latitude, longitude, adventure_id))
        else:
            conn.execute(
                'UPDATE adventures SET weather_json = ?, weather_fetched_at = ? WHERE id = ?',
                (weather_json, fetched_at or datetime.utcnow().isoformat(), adventure_id))
        conn.commit()


def delete_adventure(adventure_id, deleted_at=None):
    """Soft-delete an adventure: stamp deleted_at instead of removing the row
    so a mistaken delete can be undone. After the delete window expires the
    row is hard-purged (see purge_expired_deletes)."""
    with get_db() as conn:
        conn.execute(
            'UPDATE adventures SET deleted_at = ? WHERE id = ?',
            (deleted_at or datetime.utcnow().isoformat(), adventure_id)
        )
        conn.commit()


def undo_delete(adventure_id):
    """Restore a soft-deleted adventure by clearing its deleted_at stamp."""
    with get_db() as conn:
        conn.execute(
            'UPDATE adventures SET deleted_at = NULL WHERE id = ? AND deleted_at IS NOT NULL',
            (adventure_id,)
        )
        conn.commit()


def purge_expired_deletes(window_hours=24):
    """Lazily hard-delete soft-deleted adventures whose undo window has passed.
    Call from cheap request handlers (home/health); no background job needed on
    the free tier. Returns the number of rows purged."""
    cutoff = (datetime.utcnow() - timedelta(hours=window_hours)).isoformat()
    with get_db() as conn:
        rows = conn.execute(
            'SELECT id FROM adventures WHERE deleted_at IS NOT NULL AND deleted_at < ?',
            (cutoff,)
        ).fetchall()
        for row in rows:
            conn.execute('DELETE FROM attendees WHERE adventure_id = ?', (row['id'],))
            conn.execute('DELETE FROM adventures WHERE id = ?', (row['id'],))
        conn.commit()
        return len(rows)


def get_adventure_by_share_id(share_id, include_deleted=False):
    """Return an adventure by share_id, or None.

    By default only live (non-deleted) adventures are returned, matching the
    public view. Pass include_deleted=True when you need to render the
    deleted-state page so the shared link can offer an undo."""
    with get_db() as conn:
        if include_deleted:
            return conn.execute(
                'SELECT * FROM adventures WHERE share_id = ?', (share_id,)
            ).fetchone()
        return conn.execute(
            'SELECT * FROM adventures WHERE share_id = ? AND deleted_at IS NULL',
            (share_id,)
        ).fetchone()


def get_adventure_by_id(adventure_id):
    with get_db() as conn:
        return conn.execute(
            'SELECT * FROM adventures WHERE id = ?', (adventure_id,)
        ).fetchone()


def get_all_adventures(show_past=False):
    # Order by event date/time (not creation time) so the home list reads
    # "soonest adventure first". date is stored ISO (YYYY-MM-DD) so it sorts
    # correctly as text; created_at DESC breaks ties for same-time events.
    # Soft-deleted adventures (deleted_at IS NULL) are excluded.
    # By default only shows upcoming adventures (date >= today).
    # Each row carries going/interested counts so home cards can show "N going".
    with get_db() as conn:
        if show_past:
            rows = conn.execute(
                'SELECT a.*, '
                '(SELECT COUNT(*) FROM attendees at WHERE at.adventure_id = a.id AND at.status = \'going\') as going_count, '
                '(SELECT COUNT(*) FROM attendees at WHERE at.adventure_id = a.id AND at.status = \'interested\') as interested_count '
                'FROM adventures a WHERE a.deleted_at IS NULL '
                'ORDER BY a.date ASC, a.time ASC, a.created_at DESC'
            ).fetchall()
        else:
            rows = conn.execute(
                'SELECT a.*, '
                '(SELECT COUNT(*) FROM attendees at WHERE at.adventure_id = a.id AND at.status = \'going\') as going_count, '
                '(SELECT COUNT(*) FROM attendees at WHERE at.adventure_id = a.id AND at.status = \'interested\') as interested_count '
                "FROM adventures a WHERE a.deleted_at IS NULL AND a.date >= date('now') "
                'ORDER BY a.date ASC, a.time ASC, a.created_at DESC'
            ).fetchall()
        return rows


def get_all_adventures_for_manage():
    """List EVERY adventure (including soft-deleted ones) for the /manage page,
    newest first, with a going-count + total-attendee count per adventure so test
    junk is easy to spot. Unlike get_all_adventures, deleted rows are included —
    that's the point of a manage view: see everything, undo or delete test junk."""
    with get_db() as conn:
        rows = conn.execute(
            'SELECT a.*, '
            '(SELECT COUNT(*) FROM attendees at WHERE at.adventure_id = a.id AND at.status = ?) as going_count, '
            '(SELECT COUNT(*) FROM attendees at WHERE at.adventure_id = a.id) as total_attendees '
            'FROM adventures a '
            'ORDER BY a.created_at DESC',
            ('going',)
        ).fetchall()
        return rows

def save_weather(adventure_id, weather_json, fetched_at=None, latitude=None, longitude=None):
    """Store or clear the cached weather payload and optionally the geocoded
    coordinates. None for weather_json clears the cache (e.g. on edit, so a
    location/date typo fix refetches on the next view)."""
    with get_db() as conn:
        if latitude is not None and longitude is not None:
            conn.execute(
                'UPDATE adventures SET weather_json = ?, weather_fetched_at = ?, '
                'latitude = ?, longitude = ? WHERE id = ?',
                (weather_json, fetched_at or datetime.utcnow().isoformat(),
                 latitude, longitude, adventure_id))
        else:
            conn.execute(
                'UPDATE adventures SET weather_json = ?, weather_fetched_at = ? WHERE id = ?',
                (weather_json, fetched_at or datetime.utcnow().isoformat(), adventure_id))
        conn.commit()


def delete_adventure(adventure_id, deleted_at=None):
    """Soft-delete an adventure: stamp deleted_at instead of removing the row
    so a mistaken delete can be undone. After the delete window expires the
    row is hard-purged (see purge_expired_deletes)."""
    with get_db() as conn:
        conn.execute(
            'UPDATE adventures SET deleted_at = ? WHERE id = ?',
            (deleted_at or datetime.utcnow().isoformat(), adventure_id)
        )
        conn.commit()


def undo_delete(adventure_id):
    """Restore a soft-deleted adventure by clearing its deleted_at stamp."""
    with get_db() as conn:
        conn.execute(
            'UPDATE adventures SET deleted_at = NULL WHERE id = ? AND deleted_at IS NOT NULL',
            (adventure_id,)
        )
        conn.commit()


def purge_expired_deletes(window_hours=24):
    """Lazily hard-delete soft-deleted adventures whose undo window has passed.
    Call from cheap request handlers (home/health); no background job needed on
    the free tier. Returns the number of rows purged."""
    cutoff = (datetime.utcnow() - timedelta(hours=window_hours)).isoformat()
    with get_db() as conn:
        rows = conn.execute(
            'SELECT id FROM adventures WHERE deleted_at IS NOT NULL AND deleted_at < ?',
            (cutoff,)
        ).fetchall()
        for row in rows:
            conn.execute('DELETE FROM attendees WHERE adventure_id = ?', (row['id'],))
            conn.execute('DELETE FROM adventures WHERE id = ?', (row['id'],))
        conn.commit()
        return len(rows)


def get_adventure_by_share_id(share_id, include_deleted=False):
    """Return an adventure by share_id, or None.

    By default only live (non-deleted) adventures are returned, matching the
    public view. Pass include_deleted=True when you need to render the
    deleted-state page so the shared link can offer an undo."""
    with get_db() as conn:
        if include_deleted:
            return conn.execute(
                'SELECT * FROM adventures WHERE share_id = ?', (share_id,)
            ).fetchone()
        return conn.execute(
            'SELECT * FROM adventures WHERE share_id = ? AND deleted_at IS NULL',
            (share_id,)
        ).fetchone()


def get_adventure_by_id(adventure_id):
    with get_db() as conn:
        return conn.execute(
            'SELECT * FROM adventures WHERE id = ?', (adventure_id,)
        ).fetchone()


def get_all_adventures(show_past=False):
    # Order by event date/time (not creation time) so the home list reads
    # "soonest adventure first". date is stored ISO (YYYY-MM-DD) so it sorts
    # correctly as text; created_at DESC breaks ties for same-time events.
    # Soft-deleted adventures (deleted_at IS NULL) are excluded.
    # By default only shows upcoming adventures (date >= today).
    # Each row carries going/interested counts so home cards can show "N going".
    with get_db() as conn:
        if show_past:
            rows = conn.execute(
                'SELECT a.*, '
                '(SELECT COUNT(*) FROM attendees at WHERE at.adventure_id = a.id AND at.status = \'going\') as going_count, '
                '(SELECT COUNT(*) FROM attendees at WHERE at.adventure_id = a.id AND at.status = \'interested\') as interested_count '
                'FROM adventures a WHERE a.deleted_at IS NULL '
                'ORDER BY a.date ASC, a.time ASC, a.created_at DESC'
            ).fetchall()
        else:
            rows = conn.execute(
                'SELECT a.*, '
                '(SELECT COUNT(*) FROM attendees at WHERE at.adventure_id = a.id AND at.status = \'going\') as going_count, '
                '(SELECT COUNT(*) FROM attendees at WHERE at.adventure_id = a.id AND at.status = \'interested\') as interested_count '
                "FROM adventures a WHERE a.deleted_at IS NULL AND a.date >= date('now') "
                'ORDER BY a.date ASC, a.time ASC, a.created_at DESC'
            ).fetchall()
        return rows


def get_all_adventures_for_manage():
    """List EVERY adventure (including soft-deleted ones) for the /manage page,
    newest first, with a going-count + total-attendee count per adventure so test
    junk is easy to spot. Unlike get_all_adventures, deleted rows are included —
    that's the point of a manage view: see everything, undo or delete test junk."""
    with get_db() as conn:
        rows = conn.execute(
            'SELECT a.*, '
            '(SELECT COUNT(*) FROM attendees at WHERE at.adventure_id = a.id AND at.status = ?) as going_count, '
            '(SELECT COUNT(*) FROM attendees at WHERE at.adventure_id = a.id) as total_attendees '
            'FROM adventures a '
            'ORDER BY a.created_at DESC',
            ('going',)
        ).fetchall()
        return rows


