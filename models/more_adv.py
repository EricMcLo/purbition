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

