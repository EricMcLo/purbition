from .core import get_db


def get_cost_items(adventure_id):
    """Return an adventure's cost breakdown line items (label + amount), in order."""
    with get_db() as conn:
        rows = conn.execute(
            'SELECT * FROM cost_items WHERE adventure_id = ? ORDER BY sort_order ASC, id ASC',
            (adventure_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def add_cost_item(adventure_id, label, amount, sort_order=None):
    """Add a cost breakdown line item. Returns the new row's id."""
    if sort_order is None:
        with get_db() as conn:
            mx = conn.execute(
                'SELECT COALESCE(MAX(sort_order), 0) FROM cost_items WHERE adventure_id = ?',
                (adventure_id,)
            ).fetchone()[0]
            sort_order = mx + 1
    with get_db() as conn:
        cur = conn.execute(
            'INSERT INTO cost_items (adventure_id, label, amount, sort_order) VALUES (?, ?, ?, ?)',
            (adventure_id, label, amount, sort_order)
        )
        conn.commit()
        return cur.lastrowid


def delete_cost_item(adventure_id, item_id):
    """Delete a cost breakdown line item. Returns True if deleted."""
    with get_db() as conn:
        cur = conn.execute(
            'DELETE FROM cost_items WHERE id = ? AND adventure_id = ?',
            (item_id, adventure_id)
        )
        conn.commit()
        return cur.rowcount > 0


def _parse_cost_amount(amount):
    """Best-effort parse of a cost item's amount to a number for a running total.
    Strips non-numeric chars, handles '$xx', 'xx', '~xx', 'xx.xx'. Returns a
    number (0 if unparseable, caller decides how to display)."""
    import re
    m = re.search(r'[-+]?\d+(\.\d+)?', str(amount))
    return float(m.group(0)) if m else 0.0


def get_cost_item_total(adventure_id):
    """Sum of a cost breakdown's line-item amounts (best-effort parse)."""
    items = get_cost_items(adventure_id)
    total = sum(_parse_cost_amount(i['amount']) for i in items)
    return total


# ---------------------------------------------------------------------------
# Cost splits — expenses, per-attendee Venmo handles, equal-split math
# ---------------------------------------------------------------------------

def get_expenses(adventure_id):
    """Return an adventure's expenses with payer info, newest first.

    Each row is enriched with a `payer_name` (the attendee's name) so the
    template doesn't have to do a second lookup per row.
    """
    with get_db() as conn:
        rows = conn.execute(
            '''SELECT e.*, a.name AS payer_name
               FROM expenses e
               JOIN attendees a ON a.id = e.paid_by_attendee_id
               WHERE e.adventure_id = ?
               ORDER BY e.created_at DESC, e.id DESC''',
            (adventure_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def add_expense(adventure_id, paid_by_attendee_id, label, amount):
    """Add an expense. Returns the new row's id."""
    with get_db() as conn:
        cur = conn.execute(
            'INSERT INTO expenses (adventure_id, paid_by_attendee_id, label, amount) VALUES (?, ?, ?, ?)',
            (adventure_id, paid_by_attendee_id, label, amount)
        )
        conn.commit()
        return cur.lastrowid


def delete_expense(adventure_id, expense_id):
    """Delete an expense. Returns True if deleted."""
    with get_db() as conn:
        cur = conn.execute(
            'DELETE FROM expenses WHERE id = ? AND adventure_id = ?',
            (expense_id, adventure_id)
        )
        conn.commit()
        return cur.rowcount > 0


def set_attendee_venmo(attendee_id, handle):
    """Set an attendee's Venmo handle. Empty/None clears it."""
    clean = (handle or '').strip().lstrip('@') or None
    with get_db() as conn:
        conn.execute('UPDATE attendees SET venmo_handle = ? WHERE id = ?', (clean, attendee_id))
        conn.commit()


def set_attendee_splits(attendee_id, splits):
    """Toggle whether an attendee is in the equal-split math (0 = opt out)."""
    val = 1 if splits else 0
    with get_db() as conn:
        conn.execute('UPDATE attendees SET splits = ? WHERE id = ?', (val, attendee_id))
        conn.commit()


def compute_splits(adventure_id):
    """Equal-split math for an adventure.

    Returns a dict:
      total:        float total of all expenses (parsed)
      splitter_ids: [int] of attendee ids in the split
      per_share:    float each splitter owes
      rows:         [{'attendee_id', 'name', 'paid', 'share', 'net', 'venmo_handle', 'splits'}]
                    net > 0: they're owed X (others pay them)
                    net < 0: they owe X (they pay someone)
                    net == 0: even
      owes_map:     { attendee_id: [(creditor_attendee_id, amount), ...] }
                    for each attendee who owes, the creditors + amounts.
                    Venmo deeplink per (debtor, creditor) row.

    Splitters are "going" attendees with splits=1. If there are zero splitters
    or zero expenses, total is 0 and rows reflect the no-spend case.
    """
    expenses = get_expenses(adventure_id)
    total = sum(_parse_cost_amount(e['amount']) for e in expenses)

    with get_db() as conn:
        splitters = [dict(r) for r in conn.execute(
            "SELECT id, name, venmo_handle, splits FROM attendees "
            "WHERE adventure_id = ? AND status = 'going' AND splits = 1",
            (adventure_id,)
        ).fetchall()]

    if not splitters or total == 0:
        return {
            'total': 0.0,
            'splitter_ids': [],
            'per_share': 0.0,
            'rows': [],
            'owes_map': {},
        }

    per_share = total / len(splitters)
    paid_by_id = {}
    for e in expenses:
        paid_by_id.setdefault(e['paid_by_attendee_id'], 0.0)
        paid_by_id[e['paid_by_attendee_id']] += _parse_cost_amount(e['amount'])

    # Rows for the people who participate in settlement:
    #  - Each *splitter* pays per_share and gets credit for what they paid.
    #  - A *non-splitter payer* (anyone who paid an expense but isn't `going`
    #    with splits=1, e.g. an 'interested' friend the host logged) is a pure
    #    creditor: they're owed their full outlay and don't share in the pot.
    #    This keeps the equal-split model while letting the host log payments
    #    before everyone RSVPs 'Going'.
    splitter_set = {s['id'] for s in splitters}
    rows = []
    for s in splitters:
        paid = paid_by_id.get(s['id'], 0.0)
        rows.append({
            'attendee_id': s['id'],
            'name': s['name'],
            'paid': paid,
            'share': per_share,
            'net': paid - per_share,   # owed to them (+) / they owe (−)
            'venmo_handle': s['venmo_handle'],
            'splits': 1,
        })
    for payer_id, amt in paid_by_id.items():
        if payer_id in splitter_set:
            continue
        with get_db() as conn:
            payer = conn.execute(
                'SELECT id, name, venmo_handle FROM attendees WHERE id = ?',
                (payer_id,)
            ).fetchone()
        if not payer:
            continue
        rows.append({
            'attendee_id': payer['id'],
            'name': payer['name'],
            'paid': amt,
            'share': 0.0,
            'net': amt,                # fully owed, not splitting
            'venmo_handle': payer['venmo_handle'],
            'splits': 0,
        })

    # Greedy debt settlement: each debtor (net<0) pays creditors (net>0)
    # until everyone is even. We round to cents to avoid penny drift.
    # IMPORTANT: work on *surrogate* copies, NOT the rows we display, so the
    # display `net` keeps its real value ("Eric owed $40") after we settle.
    debtors = sorted([dict(r) for r in rows if r['net'] < -0.005], key=lambda r: r['net'])
    creditors = sorted([dict(r) for r in rows if r['net'] > 0.005], key=lambda r: -r['net'])
    owes_map = {r['attendee_id']: [] for r in rows}
    i = j = 0
    while i < len(debtors) and j < len(creditors):
        d = debtors[i]
        c = creditors[j]
        pay = min(-d['net'], c['net'])
        pay = round(pay, 2)
        if pay > 0:
            owes_map[d['attendee_id']].append((c['attendee_id'], pay))
            d['net'] += pay
            c['net'] -= pay
        if abs(d['net']) < 0.005:
            i += 1
        if abs(c['net']) < 0.005:
            j += 1

    return {
        'total': total,
        'splitter_ids': [s['id'] for s in splitters],
        'per_share': per_share,
        'rows': rows,
        'owes_map': owes_map,
    }


# ---------------------------------------------------------------------------
# Group packing list — shared gear board, stickied to who's bringing it
# ---------------------------------------------------------------------------

