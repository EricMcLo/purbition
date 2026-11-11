import secrets

from .core import get_db


def add_attendee(adventure_id, name, status='going', token=None, driving=0,
                seats=None, departure_time=None, departure_location=None,
                needs_ride=0, plus_one_name=None):
    """Add or update an attendee. Returns the token that identifies them.

    The token ties an attendee to the browser that RSVP'd (via cookie), so that
    same person can change their own status later. Old rows saved before tokens
    existed have token=NULL and get claimed by matching name.

    ``driving`` is a 0/1 flag (1 = "I can drive"). Only meaningful for people
    whose status is 'going' — callers pass 0 for any other status.

    F5 carpool fields (per `docs/f5-carpool-design-v2.md`):
    - seats, departure_time, departure_location: driver-side fields
    - needs_ride: rider-side flag (0/1)
    - plus_one_name: optional name of a +1 guest the attendee is bringing.
      Only stored for 'going' attendees.

    Lifecycle invariants enforced at the end of this function:
    1. If driving=1, force needs_ride=0 (a driver doesn't need a ride)
    2. If needs_ride=0, clear ride_with_driver_id (no car if no need)
    3. If status != 'going', clear needs_ride and ride_with_driver_id
    4. If driving=0, clear ride_with_driver_id for all of this driver's
       claimed riders (their car is gone)
    """
    driving = 1 if driving else 0
    needs_ride = 1 if needs_ride else 0
    # Mutual exclusion: a driver doesn't need a ride.
    if driving:
        needs_ride = 0
    # Lifecycle invariant: needs_ride only makes sense for going attendees.
    if status != 'going':
        needs_ride = 0
    # Plus-one only makes sense for going attendees.
    if status != 'going':
        plus_one_name = None
    with get_db() as conn:
        # This browser already RSVP'd — update that attendee in place.
        if token:
            mine = conn.execute(
                'SELECT id FROM attendees WHERE adventure_id = ? AND token = ?',
                (adventure_id, token)
            ).fetchone()
            if mine:
                conn.execute(
                    '''UPDATE attendees
                       SET status = ?, name = ?, driving = ?,
                           seats = ?, departure_time = ?, departure_location = ?,
                           needs_ride = ?, plus_one_name = ?
                       WHERE id = ?''',
                    (status, name, driving,
                     seats, departure_time, departure_location,
                     needs_ride, plus_one_name, mine['id'])
                )
                conn.commit()
                _enforce_carpool_lifecycle(conn, mine['id'], status, driving, needs_ride)
                return token

        # Unclaimed name (legacy rows only) → update it in place.
        existing = conn.execute(
            '''SELECT id, token FROM attendees
               WHERE adventure_id = ? AND LOWER(name) = LOWER(?)''',
            (adventure_id, name)
        ).fetchone()
        if existing and existing['token'] is None:
            conn.execute(
                '''UPDATE attendees
                   SET status = ?, token = ?, driving = ?,
                       seats = ?, departure_time = ?, departure_location = ?,
                       needs_ride = ?, plus_one_name = ?
                   WHERE id = ?''',
                (status, token, driving,
                 seats, departure_time, departure_location,
                 needs_ride, plus_one_name, existing['id'])
            )
            conn.commit()
            _enforce_carpool_lifecycle(conn, existing['id'], status, driving, needs_ride)
            return token
        # Fall through: new attendee, or a name already claimed by someone else
        # (two people can share a name) → create a fresh row.

        new_token = token or secrets.token_urlsafe(16)
        conn.execute(
            '''INSERT INTO attendees
               (adventure_id, name, status, token, driving,
                seats, departure_time, departure_location, needs_ride, plus_one_name)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (adventure_id, name, status, new_token, driving,
             seats, departure_time, departure_location, needs_ride,
             plus_one_name)
        )
        conn.commit()
        return new_token


def _enforce_carpool_lifecycle(conn, attendee_id, status, driving, needs_ride):
    """Repair carpool FKs after a status / driving / needs_ride change.

    Called from add_attendee after the main write. All paths run on a single
    connection so this is atomic with the write above.
    """
    # If this attendee stopped driving, free all of their claimed riders.
    if not driving:
        conn.execute(
            '''UPDATE attendees
               SET ride_with_driver_id = NULL
               WHERE ride_with_driver_id = ?''',
            (attendee_id,)
        )
    # If this attendee is no longer 'going' OR no longer needs a ride,
    # clear their own FK.
    if status != 'going' or not needs_ride:
        conn.execute(
            '''UPDATE attendees
               SET ride_with_driver_id = NULL
               WHERE id = ?''',
            (attendee_id,)
        )
    conn.commit()


def claim_rider(adventure_id, driver_attendee_id, rider_attendee_id):
    """Driver (driver_attendee_id) claims a rider (rider_attendee_id).

    Returns (ok, message). Validates:
    - driver is going and driving=1
    - rider is going and needs_ride=1
    - rider isn't already claimed by another driver
    """
    with get_db() as conn:
        driver = conn.execute(
            'SELECT * FROM attendees WHERE id = ? AND adventure_id = ?',
            (driver_attendee_id, adventure_id)
        ).fetchone()
        rider = conn.execute(
            'SELECT * FROM attendees WHERE id = ? AND adventure_id = ?',
            (rider_attendee_id, adventure_id)
        ).fetchone()
        if not driver or not rider:
            return (False, 'Attendee not found')
        if driver['status'] != 'going' or not driver['driving']:
            return (False, 'Only drivers can claim riders')
        if rider['status'] != 'going' or not rider['needs_ride']:
            return (False, 'Rider must be going and need a ride')
        if rider['ride_with_driver_id'] and rider['ride_with_driver_id'] != driver_attendee_id:
            return (False, 'Rider is already with another driver')
        conn.execute(
            'UPDATE attendees SET ride_with_driver_id = ? WHERE id = ?',
            (driver_attendee_id, rider_attendee_id)
        )
        conn.commit()
        return (True, None)


def claim_driver(adventure_id, rider_attendee_id, driver_attendee_id):
    """Rider (rider_attendee_id) picks a driver (driver_attendee_id).

    Returns (ok, message). Validates:
    - rider is going, needs_ride=1, driving=0
    - driver is going and driving=1
    - rider isn't already claimed by another driver
    """
    with get_db() as conn:
        rider = conn.execute(
            'SELECT * FROM attendees WHERE id = ? AND adventure_id = ?',
            (rider_attendee_id, adventure_id)
        ).fetchone()
        driver = conn.execute(
            'SELECT * FROM attendees WHERE id = ? AND adventure_id = ?',
            (driver_attendee_id, adventure_id)
        ).fetchone()
        if not rider or not driver:
            return (False, 'Attendee not found')
        if rider['status'] != 'going' or not rider['needs_ride'] or rider['driving']:
            return (False, 'You must need a ride (and not be a driver) to claim a car')
        if driver['status'] != 'going' or not driver['driving']:
            return (False, 'Target is not a driver')
        if rider['ride_with_driver_id'] and rider['ride_with_driver_id'] != driver_attendee_id:
            return (False, 'You already have a driver — unclaim first')
        conn.execute(
            'UPDATE attendees SET ride_with_driver_id = ? WHERE id = ?',
            (driver_attendee_id, rider_attendee_id)
        )
        conn.commit()
        return (True, None)


def unclaim(adventure_id, current_attendee_id, rider_attendee_id):
    """Clear a rider's ride_with_driver_id.

    Valid if current is the rider (self-unclaim) OR current is the rider's
    driver (driver unclaiming their own rider).
    """
    with get_db() as conn:
        rider = conn.execute(
            'SELECT * FROM attendees WHERE id = ? AND adventure_id = ?',
            (rider_attendee_id, adventure_id)
        ).fetchone()
        if not rider:
            return (False, 'Attendee not found')
        if not rider['ride_with_driver_id']:
            return (False, 'Rider has no driver to unclaim')
        if current_attendee_id == rider['id']:
            # Self-unclaim
            pass
        elif current_attendee_id == rider['ride_with_driver_id']:
            # Driver unclaiming their own rider
            pass
        else:
            return (False, 'You cannot unclaim this person')
        conn.execute(
            'UPDATE attendees SET ride_with_driver_id = NULL WHERE id = ?',
            (rider_attendee_id,)
        )
        conn.commit()
        return (True, None)


def get_carpool_summary(adventure_id):
    """Return aggregate carpool stats: (total_seats, drivers_count, riders_unclaimed_count).

    Surplus = total_seats - riders_unclaimed_count. Positive = everyone sorted.
    """
    with get_db() as conn:
        seats_row = conn.execute(
            '''SELECT COALESCE(SUM(seats), 0) as total_seats,
                      COUNT(*) as drivers_count
               FROM attendees
               WHERE adventure_id = ? AND status = 'going' AND driving = 1''',
            (adventure_id,)
        ).fetchone()
        unclaimed_row = conn.execute(
            '''SELECT COUNT(*) as count
               FROM attendees
               WHERE adventure_id = ? AND status = 'going'
                 AND needs_ride = 1 AND ride_with_driver_id IS NULL''',
            (adventure_id,)
        ).fetchone()
        return {
            'total_seats': seats_row['total_seats'] or 0,
            'drivers_count': seats_row['drivers_count'] or 0,
            'riders_unclaimed': unclaimed_row['count'] or 0,
        }


def get_attendee_by_token(adventure_id, token):
    """Look up an attendee by their browser token (or None if unknown)."""
    if not token:
        return None
    with get_db() as conn:
        return conn.execute(
            'SELECT * FROM attendees WHERE adventure_id = ? AND token = ?',
            (adventure_id, token)
        ).fetchone()


def get_attendees(adventure_id):
    with get_db() as conn:
        return conn.execute(
            'SELECT * FROM attendees WHERE adventure_id = ? ORDER BY created_at',
            (adventure_id,)
        ).fetchall()


def get_going_count(adventure_id):
    with get_db() as conn:
        return conn.execute(
            'SELECT COUNT(*) as count FROM attendees WHERE adventure_id = ? AND status = ?',
            (adventure_id, 'going')
        ).fetchone()['count']


def update_attendee(attendee_id, **kwargs):
    """Update arbitrary fields on an attendee row.

    Only columns that exist in kwargs are updated. Used by creator carpool
    mode to edit a driver's seats, departure_time, departure_location, etc.
    """
    if not kwargs:
        return
    cols = list(kwargs.keys())
    set_clause = ', '.join(f'{k} = ?' for k in cols)
    vals = list(kwargs.values()) + [attendee_id]
    with get_db() as conn:
        conn.execute(f'UPDATE attendees SET {set_clause} WHERE id = ?', vals)
        conn.commit()


def delete_attendee(adventure_id, attendee_id):
    """Hard-delete an attendee (RSVP) from an adventure.

    Link-trusted, no-auth app: anyone holding the shared link may remove an
    attendee. Returns True if a row was actually deleted (guards the caller
    against deleting an attendee that belongs to a different adventure or
    that no longer exists).
    """
    with get_db() as conn:
        cur = conn.execute(
            'DELETE FROM attendees WHERE id = ? AND adventure_id = ?',
            (attendee_id, adventure_id)
        )
        conn.commit()
        return cur.rowcount > 0



def move_rider(rider_attendee_id, new_driver_attendee_id):
    """Move a rider to a different driver's car (creator carpool mode).

    Validates that both rider and driver exist, are going, the rider needs
    a ride, and the new driver is actually a driver. Clears the rider's
    old ride_with_driver_id and sets the new one.
    Returns (ok, message).
    """
    with get_db() as conn:
        rider = conn.execute(
            'SELECT * FROM attendees WHERE id = ?', (rider_attendee_id,)
        ).fetchone()
        driver = conn.execute(
            'SELECT * FROM attendees WHERE id = ?', (new_driver_attendee_id,)
        ).fetchone()
        if not rider or not driver:
            return (False, 'Attendee not found')
        if rider['status'] != 'going':
            return (False, 'Rider is not going to this adventure')
        if driver['status'] != 'going' or not driver['driving']:
            return (False, 'Target is not a driver')
        conn.execute(
            'UPDATE attendees SET ride_with_driver_id = ? WHERE id = ?',
            (new_driver_attendee_id, rider_attendee_id)
        )
        conn.commit()
        return (True, None)


# ---------------------------------------------------------------------------
# Cost breakdown line items
# ---------------------------------------------------------------------------

