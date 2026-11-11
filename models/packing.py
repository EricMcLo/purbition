from .core import get_db


CATEGORY_ORDER = {
    'main': 0,
    'side': 1,
    'appetizer': 2,
    'dessert': 3,
    'drinks': 4,
    'other': 5,
}

CATEGORY_EMOJI = {
    'appetizer': '🥢',
    'main': '🍗',
    'side': '🥗',
    'dessert': '🍰',
    'drinks': '🍹',
    'other': '🍽️',
}


def get_packing_items(adventure_id):
    """Return an adventure's group packing items, with claimer info,
    sorted by category (main first), then by sort_order.

    Each row is enriched with `claimed_name` (the attendee who claimed it) so
    the template can show "the cooler — Jordan" without a second lookup.
    """
    with get_db() as conn:
        rows = conn.execute(
            '''SELECT p.*, a.name AS claimed_name
               FROM packing_items p
               LEFT JOIN attendees a ON a.id = p.claimed_by_attendee_id
               WHERE p.adventure_id = ?
               ORDER BY p.sort_order ASC, p.id ASC''',
            (adventure_id,)
        ).fetchall()
        result = [dict(r) for r in rows]
        result.sort(key=lambda r: (
            CATEGORY_ORDER.get(r.get('category') or 'other', 99),
            r.get('sort_order') or 999,
        ))
        return result


def add_packing_item(adventure_id, label, category='other'):
    """Add a group packing item. If an item with the same label already
    exists (claimed or not), increment its quantity instead of creating
    a duplicate."""
    with get_db() as conn:
        existing = conn.execute(
            '''SELECT id, quantity FROM packing_items
               WHERE adventure_id = ? AND lower(label) = lower(?)''',
            (adventure_id, label.strip())
        ).fetchone()
        if existing:
            conn.execute(
                'UPDATE packing_items SET quantity = quantity + 1 WHERE id = ?',
                (existing['id'],)
            )
            conn.commit()
            return existing['id']
        # pick a sort_order one past the max
        row = conn.execute(
            'SELECT COALESCE(MAX(sort_order), 0) + 1 AS n FROM packing_items WHERE adventure_id = ?',
            (adventure_id,)
        ).fetchone()
        order = int(row['n']) if row else 1
        cur = conn.execute(
            'INSERT INTO packing_items (adventure_id, label, sort_order, category) VALUES (?, ?, ?, ?)',
            (adventure_id, label, order, category)
        )
        conn.commit()
        return cur.lastrowid


def delete_packing_item(adventure_id, item_id):
    """Delete a group packing item. Any unclaimed item (or a claim if the
    claimant wants it gone) can be removed. Returns True if deleted."""
    with get_db() as conn:
        cur = conn.execute(
            'DELETE FROM packing_items WHERE id = ? AND adventure_id = ?',
            (item_id, adventure_id)
        )
        conn.commit()
        return cur.rowcount > 0


def claim_packing_item(adventure_id, item_id, attendee_id, unclaim=False):
    """Claim a group packing item for an attendee, or unclaim it.
    Claiming a currently-unclaimed item sets its owner. Unclaiming clears the
    owner back to "needs someone". Returns True if the state changed."""
    with get_db() as conn:
        item = conn.execute(
            'SELECT * FROM packing_items WHERE id = ? AND adventure_id = ?',
            (item_id, adventure_id)
        ).fetchone()
        if not item:
            return False
        cur = conn.execute(
            'UPDATE packing_items SET claimed_by_attendee_id = ? WHERE id = ?',
            (None if unclaim else attendee_id, item_id)
        )
        conn.commit()
        return cur.rowcount > 0
