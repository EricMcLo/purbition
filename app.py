import os
import time
import json
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, Response, make_response, g, abort
from io import BytesIO
from whitenoise import WhiteNoise
from config import config
from models import init_db, get_db, create_adventure, get_adventure_by_share_id, get_all_adventures, get_all_adventures_for_manage, add_attendee, get_attendee_by_token, get_attendees, get_going_count, update_adventure, update_adventure_clearing_weather, delete_adventure, undo_delete, purge_expired_deletes, save_weather, claim_rider, claim_driver, unclaim, get_carpool_summary, update_attendee, move_rider, delete_attendee, generate_share_id, create_series_occurrences, get_series, get_cost_items, add_cost_item, delete_cost_item, get_cost_item_total, update_future_series_occurrences, soft_delete_future_series_occurrences, count_future_series_occurrences, get_expenses, add_expense, delete_expense, set_attendee_venmo, set_attendee_splits, compute_splits, get_packing_items, add_packing_item, delete_packing_item, claim_packing_item
from weather import get_weather, mountain_today
from share_card import generate_card

# Cookie that remembers which attendee this browser is (lets them change their own RSVP).
RSVP_COOKIE = 'rsvp_token'
RSVP_COOKIE_MAX_AGE = 60 * 60 * 24 * 180  # 180 days


# Create-wizard "category" picker (the DB column is still called `vibe`).
# Two groups keep the narrative simple: what you're doing outside vs who
# you're doing it with. Icons are inline SVG (lucide-style strokes).
VIBES = [
    # -- Outdoors ----------------------------------------------------------
    {'id': 'hike', 'group': 'outdoors', 'label': 'Hike & Trail Run',
     'blurb': 'Boots on, views at the top.',
     'icon': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3l4 8 5-5 5 15H2L8 3z"/></svg>'},
    {'id': 'snow', 'group': 'outdoors', 'label': 'Ski & Snow',
     'blurb': 'Powder laps and après.',
     'icon': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v18M4.1 6.6l15.8 10.8M19.9 6.6 4.1 17.4"/></svg>'},
    {'id': 'climb', 'group': 'outdoors', 'label': 'Climb & Boulder',
     'blurb': 'Cracks, crimps, and crash pads.',
     'icon': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 20 9 9l4 6 3-4 5 9H3Z"/><path d="M2 20h20"/></svg>'},
    {'id': 'paddle', 'group': 'outdoors', 'label': 'Paddle & Water',
     'blurb': 'River, lake, or ocean — get a little wet.',
     'icon': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M2 8c2-2 4-2 6 0s4 2 6 0 4-2 6 0"/><path d="M2 16c2-2 4-2 6 0s4 2 6 0 4-2 6 0"/></svg>'},
    {'id': 'getaway', 'group': 'outdoors', 'label': 'Weekend Getaway',
     'blurb': 'Overnight trips, cabins, camping.',
     'icon': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 21V8M7 21V4l10 4v13M3 21h18M22 21H21M7 21h10"/></svg>'},
    # -- People ------------------------------------------------------------
    {'id': 'sport', 'group': 'people', 'label': 'Sports & Clubs',
     'blurb': 'Volleyball, run club, pickleball, pickup.',
     'icon': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 3v18M5.5 6c2.7 3 2.7 9 0 12M18.5 6c-2.7 3-2.7 9 0 12"/></svg>'},
    {'id': 'games', 'group': 'people', 'label': 'Games & Hangs',
     'blurb': 'Game night, movie night, cozy couch.',
     'icon': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="4" width="16" height="16" rx="4"/><path d="M8.5 8.5h.01M15.5 15.5h.01M8.5 15.5h.01M15.5 8.5h.01"/></svg>'},
    {'id': 'food', 'group': 'people', 'label': 'Food & Drink',
     'blurb': 'Dinner, cookout, brewery crawl.',
     'icon': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 2v7c0 1.1.9 2 2 2h4c1.1 0 2-.9 2-2V2"/><path d="M7 2v20"/><path d="M21 15V2a5 5 0 0 0-5 5v6c0 1.1.9 2 2 2h3z"/><path d="M21 15v7"/></svg>'},
    {'id': 'party', 'group': 'people', 'label': 'Parties & Celebrations',
     'blurb': 'Birthdays, house parties, big days.',
     'icon': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a6.5 6.5 0 0 0-6.5 6.5c0 3 2.4 5.2 6.5 5.8 4.1-.6 6.5-2.8 6.5-5.8A6.5 6.5 0 0 0 12 2Z"/><path d="M12 15.5V21"/></svg>'},
    {'id': 'thanksgiving', 'group': 'people', 'label': 'Thanksgiving',
     'blurb': 'Turkey, pie, and family time.',
     'icon': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M20 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 14H6v-2h14v2zm0-4H6V8l4-4 4 4 4-4 4 4v8z"/></svg>'},
]
VIBE_IDS = {v['id'] for v in VIBES}
VIBE_LABELS = {v['id']: v['label'] for v in VIBES}
# Legacy rename: map old wizard ids to the new category labels so rows saved
# before the category rework still show a friendly name on covers/home cards.
VIBE_LABELS.update({
    'trail': 'Hike & Trail Run', 'climb': 'Climb & Boulder',
    'camp': 'Camp Out', 'paddle': 'Paddle & Water',
    'food': 'Food & Drink', 'cozy': 'Games & Hangs',
    'golden': 'Golden Hour', 'explore': 'Full Explore',
})
VIBE_GROUPS = [
    {'label': 'Outdoors', 'choices': [v for v in VIBES if v['group'] == 'outdoors']},
    {'label': 'People', 'choices': [v for v in VIBES if v['group'] == 'people']},
]




def escape_ics(value):
    """Escape text for iCalendar (RFC 5545): backslash, comma, semicolon, newline."""
    return str(value).replace('\\', '\\\\').replace(',', '\\,').replace(';', '\\;').replace('\r\n', '\\n').replace('\n', '\\n')


def _google_calendar_url(adventure, share_url=''):
    """Pre-filled Google Calendar "add event" link. A plain URL (no API key):
    calendar.google.com/calendar/render?action=TEMPLATE&...

    Mirrors the .ics route's date/time rules so both calendars agree:
      - all-day events -> date-only range (end exclusive)
      - timed events   -> HHMMSS range (+1h when no explicit end)
      - multi-day      -> through end_date
    Google reads local wall-clock times when `ctz` (the event timezone) is set,
    and the whole app assumes Mountain time, so we pass America/Denver and skip
    UTC math entirely. Returns '' when there's no date to build from.
    """
    def _get(key):
        try:
            return adventure[key]
        except (KeyError, IndexError, TypeError):
            return None

    date_iso = _get('date') or ''
    if not date_iso:
        return ''
    time_iso = _get('time') or ''
    end_date_val = _get('end_date')
    end_time_val = _get('end_time')
    name = _get('name') or ''
    location = _get('location') or ''
    description = _get('description') or ''

    date_compact = date_iso.replace('-', '')
    if time_iso:
        hhmmss = time_iso.replace(':', '') + '00'
        start = date_compact + 'T' + hhmmss
        if end_date_val:
            end_date_compact = end_date_val.replace('-', '')
            if end_time_val:
                end = end_date_compact + 'T' + end_time_val.replace(':', '') + '00'
            else:
                end = (datetime.strptime(end_date_compact, '%Y%m%d')
                       + timedelta(days=1)).strftime('%Y%m%dT000000')
        else:
            end = (datetime.strptime(date_compact + hhmmss, '%Y%m%d%H%M%S')
                   + timedelta(hours=1)).strftime('%Y%m%dT%H%M%S')
    else:
        # All-day: date-only, end exclusive.
        start = date_compact
        last_day = (end_date_val or date_iso).replace('-', '')
        end = (datetime.strptime(last_day, '%Y%m%d')
               + timedelta(days=1)).strftime('%Y%m%d')

    details = description
    if share_url:
        details = (details + '\n\n' if details else '') + share_url

    params = {
        'action': 'TEMPLATE',
        'text': name,
        'dates': f'{start}/{end}',
        'ctz': 'America/Denver',
    }
    if details:
        params['details'] = details
    if location:
        params['location'] = location
    return 'https://calendar.google.com/calendar/render?' + urlencode(params)


def _adventure_flag(adventure, column):
    """Read an opt-in INT column off an adventure row safely across the three
    row types (sqlite3.Row / turso _DictRow). Missing column or NULL -> off (0)."""
    try:
        if column not in adventure.keys():
            return 0
        val = adventure[column]
    except (KeyError, TypeError, IndexError, AttributeError):
        return 0
    try:
        return 1 if int(val) else 0
    except (TypeError, ValueError):
        return 0


def _relative_day_label(adventure, today):
    """Short 'coming up' cue for a home card given the adventure's start date and
    today (both ISO YYYY-MM-DD). Returns 'Today', 'Tomorrow', 'This Friday' (when
    the date lands within the current week), 'Next Friday' (next calendar week),
    or 'In N days' for anything further out. Multi-day trips use their start date."""
    from datetime import date as _date, timedelta as _td
    try:
        adv = _date.fromisoformat(adventure['date'])
    except (KeyError, TypeError, ValueError, IndexError, AttributeError):
        return ''
    today_d = _date.fromisoformat(today)
    delta = (adv - today_d).days
    if delta == 0:
        return 'Today'
    if delta == 1:
        return 'Tomorrow'
    if delta < 0:
        return ''
    weekday = adv.strftime('%A')
    if adv.isocalendar()[1] == today_d.isocalendar()[1]:
        return 'This ' + weekday
    if adv.isocalendar()[1] == today_d.isocalendar()[1] + 1:
        return 'Next ' + weekday
    return f'In {delta} days'


def disambiguate_name_map(attendees):
    """Return {attendee_id: display_name}. Only when two or more attendees have
    the SAME full display name does each collided row get a running-count
    disambiguator appended ('Sam', 'Sam 2', 'Sam 3'...), keeping every roster
    row unique. Unique names pass through unchanged."""
    base_counts = {}
    for a in attendees:
        name = (a['name'] or '').strip()
        base_counts[name] = base_counts.get(name, 0) + 1

    seen = {}
    out = {}
    for a in attendees:
        name = (a['name'] or '').strip()
        if base_counts.get(name, 0) <= 1:
            out[a['id']] = name
            continue
        n = seen.get(name, 0) + 1
        seen[name] = n
        out[a['id']] = f'{name} ·{n + 1}' if n else name
    return out


def format_date_filter(date_str, time_str=None):
    """Legacy full-line date formatter. Superseded by the piece filters below."""
    if not date_str:
        return ''
    try:
        dt = datetime.strptime(date_str, '%Y-%m-%d')
        formatted = dt.strftime('%a, %b %-d')
        if time_str:
            try:
                tm = datetime.strptime(time_str, '%H:%M')
                formatted += ' at ' + tm.strftime('%-I:%M %p')
            except ValueError:
                pass
        return formatted
    except ValueError:
        return date_str


def day_name_filter(date_str):
    """'Saturday'"""
    try:
        return datetime.strptime(date_str, '%Y-%m-%d').strftime('%A')
    except ValueError:
        return date_str


def day_short_filter(date_str):
    """'Sat' (short weekday, for share messages)"""
    try:
        return datetime.strptime(date_str, '%Y-%m-%d').strftime('%a')
    except ValueError:
        return date_str


def month_day_filter(date_str):
    """'Oct 17'"""
    try:
        return datetime.strptime(date_str, '%Y-%m-%d').strftime('%b %-d')
    except ValueError:
        return date_str


def month_abbr_filter(date_str):
    """'OCT' (tile header)"""
    try:
        return datetime.strptime(date_str, '%Y-%m-%d').strftime('%b').upper()
    except ValueError:
        return '??'


def day_num_filter(date_str):
    """'17' (tile number)"""
    try:
        return datetime.strptime(date_str, '%Y-%m-%d').strftime('%-d')
    except ValueError:
        return '??'


def _initials(name):
    """First letter of up to the first two name words, uppercase.
    Used by attendee-row chips (e.g. 'Jordan Blake' -> 'EL') to keep the
    carpool ride-with chip short on phone-sized attendee rows."""
    if not name:
        return ''
    parts = [p for p in name.split() if p][:2]
    return ''.join(p[0].upper() for p in parts if p)


def format_time_filter(time_str):
    """'6:30 AM'; '' when no time given"""
    if not time_str:
        return ''
    try:
        tm = datetime.strptime(time_str, '%H:%M')
        return tm.strftime('%-I:%M %p')
    except ValueError:
        return time_str


def display_cost_filter(cost):
    """Normalize a free-text cost field for display.

    Returns the original text when it's a real value; returns '' when the host
    typed a placeholder like "0", "$0", "free", "n/a", or just whitespace, so
    `{% if cost | display_cost %}` skips them and the UI never shows a stray
    `<span class="meta-cost">0</span>`. Strips the value, but doesn't change
    'real' values like '~$40/person' or '$20 each'.
    """
    if cost is None:
        return ''
    s = str(cost).strip()
    if not s:
        return ''
    if s.lower() in ('0', '$0', '$0.00', '0.00', 'free', 'n/a', 'na', 'none', '-', '—'):
        return ''
    return s


def venmo_deeplink_filter(payload):
    """Build a Venmo deeplink from a (handle, amount, note) tuple.
    Designed to be used as `(handle, amount, note) | venmo_deeplink` in a
    template, since Jinja filters take a single piped value. `venmo.com/USERNAME`
    works on desktop and mobile (mobile browsers redirect to the app)."""
    if not payload:
        return ''
    handle, amount, note = payload[0], payload[1], (payload[2] if len(payload) > 2 else '')
    if not handle:
        return ''
    h = str(handle).strip().lstrip('@')
    if not h:
        return ''
    try:
        amt = float(amount)
    except (TypeError, ValueError):
        amt = 0.0
    from urllib.parse import urlencode
    params = {'txn': 'pay', 'amount': f'{amt:.2f}'}
    if note:
        params['note'] = note[:140]  # Venmo note cap
    return f"https://venmo.com/{h}?{urlencode(params)}"


def form_cost_or_none():
    """Read the cost form field and normalize '0', '$0', 'free' to None.
    Mirrors display_cost_filter so the DB never holds a meaningless value."""
    from flask import request
    return display_cost_filter(request.form.get('cost', '')) or None


def validate_adventure_form(name, date, time, location, description, packing_list=None, tagline=None, end_date=None, end_time=None):
    """Shared validation for create + edit. Returns list of error strings."""
    errors = []
    if not name:
        errors.append('Name is required')
    if not date:
        errors.append('Date is required')
    if not location:
        errors.append('Location is required')
    if len(name) > 200:
        errors.append('Name must be 200 characters or less')
    if len(location) > 200:
        errors.append('Location must be 200 characters or less')
    if len(description) > 2000:
        errors.append('Description must be 2000 characters or less')
    if len(packing_list or '') > 2000:
        errors.append('Packing list must be 2000 characters or less')
    if len(tagline or '') > 200:
        errors.append('Share one-liner must be 200 characters or less')
    # Multi-day: end_date is optional. When set, must be on/after date and parseable.
    if end_date:
        try:
            end_d = datetime.strptime(end_date, '%Y-%m-%d').date()
            start_d = datetime.strptime(date, '%Y-%m-%d').date()
            if end_d < start_d:
                errors.append('End date must be on or after the start date')
        except ValueError:
            errors.append('End date must be in YYYY-MM-DD format')
    if end_time and not end_date:
        errors.append('End time requires an end date')
    return errors


def create_app(config_name=None):
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'development')

    app = Flask(__name__)
    app.config.from_object(config[config_name])

    # WhiteNoise for static files (required on Render/gunicorn)
    app.wsgi_app = WhiteNoise(app.wsgi_app, root='static/', prefix='static/')

    # --- Static cache-busting (content hash) ---
    # CSS/JS are served with a long max-age but NO cache-busting (the URL never
    # changes), so a phone that fetched a stylesheet once can keep serving a
    # stale copy for hours — that's how a shipped CSS fix can fail to appear for
    # a friend (seen on iOS Safari with the edit-form checkbox fix, Aug 31).
    # Version the asset URLs by a hash of their bytes: whenever a file changes
    # the hash changes, so every phone fetches the fresh file on the next load.
    STATIC_VERSIONED = ('style.css', 'palettes.css', 'app.js')

    def _compute_static_version():
        h = hashlib.sha1()
        base = Path(__file__).parent / 'static'
        for name in STATIC_VERSIONED:
            try:
                h.update((base / name).read_bytes())
            except OSError:
                pass
        return h.hexdigest()[:10]

    # Compute once at startup (cheap: ~90KB of small files); the version only
    # changes on redeploy, so we don't re-hash on every request.
    _static_version_val = _compute_static_version()

    @app.context_processor
    def _inject_static_version():
        return {'static_version': _static_version_val}

    with app.app_context():
        init_db()

    # --- Request timing (Server-Timing header) ---
    # Each request gets a wall-clock start and a running DB-time accumulator
    # (g.db_ms is added to by `get_db()` in models.py on every context exit).
    # `after_request` emits the W3C `Server-Timing` header so a friend can open
    # DevTools → Network → click the request → see where the seconds went.
    # Three metrics:
    #   db      = time inside `get_db()` context managers (SQL round-trips)
    #   non_db  = total - db (Python render, jinja, network, everything else)
    #   total   = wall-clock from request entry to response built
    @app.before_request
    def _start_timer():
        g.start = time.monotonic()
        g.db_ms = 0.0

    @app.after_request
    def _emit_server_timing(response):
        if hasattr(g, 'start'):
            total_ms = (time.monotonic() - g.start) * 1000
            db_ms = getattr(g, 'db_ms', 0.0)
            response.headers['Server-Timing'] = (
                f'db;dur={db_ms:.1f}, '
                f'non_db;dur={max(total_ms - db_ms, 0):.1f}, '
                f'total;dur={total_ms:.1f}'
            )
        return response

    @app.after_request
    def _security_headers(response):
        # Conservative defense-in-depth for a link-trusted, server-rendered app.
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Cross-Origin-Opener-Policy'] = 'same-origin'
        response.headers['Permissions-Policy'] = (
            'geolocation=(), camera=(), microphone=()'
        )
        # NOTE: CSP deliberately skipped — templates/base.html runs an inline
        # pre-paint theme <script> (needs a nonce/hash dance) and getting it
        # wrong pre-launch would break the site. HSTS deliberately skipped
        # (Cloudflare handles https; a bad header can hard-lock the domain).
        return response

    def _host_from_header(value):
        """Pull the host out of an Origin/Referer header, or None if absent/
        malformed. Used to reject cross-site (CSRF) mutations while keeping
        curl/smoke-test and header-less clients working."""
        if not value:
            return None
        from urllib.parse import urlparse
        try:
            return urlparse(value).netloc
        except ValueError:
            return None

    @app.before_request
    def _csrf_guard():
        # Only state-changing requests need the check; GETs (viewing) are fine.
        if request.method not in ('POST', 'PUT', 'PATCH', 'DELETE'):
            return None
        # A same-site submission has no Origin header and a Referer on our
        # host, OR an Origin header on our host. Headless clients (curl) send
        # neither — allow those too (this is a link-trusted, no-auth app).
        origin = _host_from_header(request.headers.get('Origin'))
        referer = _host_from_header(request.headers.get('Referer'))
        if origin and origin != request.host:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'error': 'Cross-site request blocked'}), 403
            return 'Cross-site request blocked', 403
        if referer and referer != request.host:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'error': 'Cross-site request blocked'}), 403
            return 'Cross-site request blocked', 403
        return None

    @app.route('/health')
    def health():
        """Lightweight liveness check for Render's health-check monitor.

        We probe the database (a trivial SELECT 1) because that's the thing
        that actually breaks in practice — if Turso is unreachable, this
        returns 503 and Render marks the instance unhealthy.
        """
        try:
            with get_db() as conn:
                conn.execute('SELECT 1')
        except Exception:
            return jsonify({'status': 'error', 'db': 'unreachable'}), 503
        # Lazy purge: hard-delete soft-deleted adventures past their undo window.
        try:
            purge_expired_deletes()
        except Exception:
            app.logger.warning('lazy purge failed in health', exc_info=True)
        return jsonify({'status': 'ok', 'db': 'ok'})

    @app.route('/')
    def index():
        # Home shows current (upcoming or in-progress) adventures first, then a
        # divider and all past adventures beneath it. Multi-day trips count as
        # current until their end date has fully passed.
        # An adventure is "past" only when its last moment has actually
        # passed. Multi-day trips: past once end_date < today. Single-day
        # with a time: past once (date < today) OR (date == today AND
        # time <= now). Single-day all-day: past once date < today.
        from datetime import datetime as _dt, timezone as _tz
        from zoneinfo import ZoneInfo as _ZoneInfo
        # Compute "now" in Mountain time (America/Denver), the timezone this
        # app's trips actually happen in. The prod server runs in UTC, so
        # datetime.now() would roll today forward at 6pm Mountain and wrongly
        # mark an 8pm trip as already past. Using a tz-aware "now" in
        # America/Denver keeps the past/upcoming split correct on every host.
        _mnt = _ZoneInfo('America/Denver')
        now_dt = _dt.now(_mnt)
        today = now_dt.strftime('%Y-%m-%d')
        now_hhmm = now_dt.strftime('%H:%M')
        all_rows = get_all_adventures(show_past=True)  # date ASC (soonest first)
        # Decorate each adventure with safe end_date/end_time for the template.
        # Old rows (pre-migration) won't have these columns; the safe access
        # returns None so the template can branch with `{% if a.end_date %}`.
        current, past = [], []
        for a in all_rows:
            try:
                end_date = a['end_date']
                end_time = a['end_time']
            except (KeyError, AttributeError, IndexError):
                end_date, end_time = None, None
            item = {'row': a, 'end_date': end_date, 'end_time': end_time}
            is_past = False
            if end_date:
                # Multi-day: the trip spans the whole end_date. Past once
                # the day after the end_date is here (matches iCal convention).
                is_past = end_date < today
            else:
                # Single-day. With a time: past once that time has passed.
                # All-day: past once the day is over.
                adv_date = a['date']
                adv_time = a['time'] if 'time' in a.keys() else None
                if adv_date < today:
                    is_past = True
                elif adv_date == today and adv_time and adv_time <= now_hhmm:
                    is_past = True
            # Relative-time cue so upcoming cards read "This Friday" / "Tomorrow".
            if not is_past:
                item['relative'] = _relative_day_label(a, today)
            if is_past:
                past.append(item)
            else:
                current.append(item)
        past.sort(key=lambda item: item['row']['date'], reverse=True)  # most recent first
        return render_template('index.html', adventures=current, past=past,
                               vibe_labels=VIBE_LABELS)

    @app.route('/manage')
    def manage():
        # A link-trusted, no-auth "admin" view: list EVERY adventure (incl.
        # soft-deleted) newest-first so test junk is easy to spot and clean up.
        # There's no login gate — consistent with the app's "anyone with the
        # link" model. Actions reuse the existing soft-delete + undo routes.
        rows = get_all_adventures_for_manage()
        items = []
        for a in rows:
            try:
                end_date = a['end_date']
                end_time = a['end_time']
            except (KeyError, AttributeError, IndexError):
                end_date, end_time = None, None
            try:
                deleted_at = a['deleted_at']
            except (KeyError, AttributeError, IndexError):
                deleted_at = None
            items.append({
                'adventure': a,
                'end_date': end_date,
                'end_time': end_time,
                'deleted': bool(deleted_at),
                'share_url': request.url_root.rstrip('/') + url_for('view_adventure', share_id=a['share_id']),
            })
        return render_template('manage.html', items=items)

    @app.route('/create', methods=['GET'], strict_slashes=False)
    def create_form():
        return render_template('create.html',
                               vibes=VIBES,
                               vibe_groups=VIBE_GROUPS,
                               form_action=url_for('create_adventure_route'),
                               submit_label='Create Adventure',
                               cancel_url=url_for('index'),
                               show_weather=1)

    @app.route('/create', methods=['POST'], strict_slashes=False)
    def create_adventure_route():
        name = request.form.get('name', '').strip()
        date = request.form.get('date', '').strip()
        time = request.form.get('time', '').strip()
        location = request.form.get('location', '').strip()
        description = request.form.get('description', '').strip()
        packing_list = request.form.get('packing_list', '').strip()
        carpool = 1 if request.form.get('carpool') else 0
        tagline = request.form.get('tagline', '').strip()
        show_weather = 1 if request.form.get('show_weather') else 0
        show_splits = 1 if request.form.get('show_splits') else 0
        show_gear = 1 if request.form.get('show_gear') else 0
        vibe = request.form.get('vibe', '').strip()
        if vibe not in VIBE_IDS:
            vibe = ''
        cover_image = request.form.get('cover_image', '').strip() or None
        end_date = request.form.get('end_date', '').strip() or None
        end_time = request.form.get('end_time', '').strip() or None
        cost = form_cost_or_none()
        # Recurring events: optional cadence + how many future occurrences to generate.
        recurrence_rule = request.form.get('recurrence_rule', '').strip()
        if recurrence_rule not in ('weekly', 'biweekly', 'monthly'):
            recurrence_rule = ''
        occ_count_raw = request.form.get('occurrence_count', '').strip()
        try:
            occ_count = int(occ_count_raw)
        except (TypeError, ValueError):
            occ_count = 0
        # Boundary: cap how many future occurrences a single create can generate,
        # so a stray/large request can't flood the DB with rows. The wizard only
        # offers up to 12; the server is the real gate.
        MAX_OCCURRENCES = 26
        if recurrence_rule and occ_count < 1:
            occ_count = 6  # sensible default if a cadence was picked but no count
        occ_count = min(max(occ_count, 0), MAX_OCCURRENCES)

        errors = validate_adventure_form(name, date, time, location, description, packing_list, tagline, end_date, end_time)

        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('create.html',
                                   name=name, date=date, time=time,
                                   location=location, description=description,
                                   packing_list=packing_list,
                                   carpool=carpool,
                                   tagline=tagline,
                                   show_weather=show_weather,
                                   show_splits=show_splits,
                                   show_gear=show_gear,
                                   end_date=end_date, end_time=end_time,
                                   cost=cost,
                                   cover_image=cover_image,
                                   recurrence_rule=recurrence_rule,
                                   occurrence_count=str(occ_count),
vibe=vibe, vibes=VIBES,
                                       vibe_groups=VIBE_GROUPS,
                                       form_action=url_for('create_adventure_route'),
                                       submit_label='Create Adventure',
                                       cancel_url=url_for('index')), 400

        if recurrence_rule:
            # Recurring: this first adventure opens a series, then we generate
            # `occ_count` future occurrences sharing the same series_id.
            series_id = generate_share_id()
            adventure_id, share_id = create_adventure(name, date, time, location, description, vibe, packing_list, carpool, tagline, show_weather, end_date, end_time, cost, series_id=series_id, recurrence_rule=recurrence_rule, show_splits=show_splits, show_gear=show_gear, cover_image=cover_image)
            extra_share_ids = create_series_occurrences(name, date, time, location, description, vibe, packing_list, carpool, tagline, show_weather, end_date, end_time, cost, series_id, recurrence_rule, occ_count, show_splits=show_splits, show_gear=show_gear)
            flash(f'Created a {recurrence_rule} series with {occ_count + 1} upcoming occurrences.', 'success')
            return redirect(url_for('view_adventure', share_id=share_id))

        adventure_id, share_id = create_adventure(name, date, time, location, description, vibe, packing_list, carpool, tagline, show_weather, end_date, end_time, cost, show_splits=show_splits, show_gear=show_gear, cover_image=cover_image)
        return redirect(url_for('view_adventure', share_id=share_id))

    @app.route('/og/<share_id>.png')
    def og_image(share_id):
        """Open Graph share card (PNG). Sharing apps fetch this URL by GET and
        show it as the link preview image. Rendered server-side with Pillow +
        the adventure's vibe gradient + bundled Karla/Fraunces fonts."""
        adventure = get_adventure_by_share_id(share_id)
        if not adventure:
            abort(404)

        going = get_going_count(adventure['id'])

        try:
            when = f"{day_name_filter(adventure['date'])}, {month_day_filter(adventure['date'])}"
            end_date = adventure['end_date'] if 'end_date' in adventure.keys() else None
            if end_date and end_date != adventure['date']:
                when += f" – {day_name_filter(end_date)}, {month_day_filter(end_date)}"
            if adventure['time']:
                when += f" · {format_time_filter(adventure['time'])}"
            else:
                when += " · All day"
        except (KeyError, AttributeError, IndexError):
            when = ""
        try:
            location = adventure['location']
        except (KeyError, AttributeError, IndexError):
            location = ""
        try:
            vibe = adventure['vibe'] or ''
        except (KeyError, AttributeError, IndexError):
            vibe = ''

        going_text = f"{going} {'person going' if going == 1 else 'people going'}"
        img = generate_card(adventure['name'], when, location, going_text, vibe)

        buf = BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)
        resp = make_response(buf.getvalue())
        resp.headers['Content-Type'] = 'image/png'
        # Short cache so the 'X going' count updates on the next share. iMessage
        # itself caches aggressively, but any time a friend re-shares the link
        # (or someone opens it again past this window) the count is fresh.
        # 2min is short enough for a club meetup to feel live, long enough to
        # spare the server if a thread re-renders the preview rapidly.
        resp.headers['Cache-Control'] = 'public, max-age=120'
        return resp

    @app.route('/adventure/<share_id>')
    def view_adventure(share_id):
        try:
            adventure = get_adventure_by_share_id(share_id, include_deleted=True)
        except Exception as e:
            app.logger.error(f"get_adventure_by_share_id failed: {e}")
            return render_template('errors/500.html', error=str(e)), 500
        if not adventure:
            return render_template('errors/404.html'), 404

        try:
            attendees = get_attendees(adventure['id'])
            going_count = get_going_count(adventure['id'])
            my_rsvp = get_attendee_by_token(adventure['id'], request.cookies.get(RSVP_COOKIE))
            name_map = disambiguate_name_map(attendees)
        except Exception as e:
            app.logger.error(f"adventure data fetch failed: {e}")
            return render_template('errors/500.html', error=str(e)), 500

        # F5 carpool: group attendees into drivers + unclaimed riders for the card.
        drivers = []
        unclaimed_riders = []
        try:
            for a in attendees:
                if a['status'] != 'going':
                    continue
                # Safe access across all 3 row types
                try:
                    driving = 1 if a['driving'] else 0
                    needs_ride = 1 if a['needs_ride'] else 0
                    ride_with = a['ride_with_driver_id'] if 'ride_with_driver_id' in a.keys() else None
                except (KeyError, AttributeError, IndexError):
                    driving, needs_ride, ride_with = 0, 0, None
                if driving:
                    riders = [
                        r for r in attendees
                        if r['status'] == 'going'
                        and ('needs_ride' in r.keys() and r['needs_ride'])
                        and ('ride_with_driver_id' in r.keys() and r['ride_with_driver_id'] == a['id'])
                    ]
                    drivers.append({**dict(a), 'riders': riders,
                                    'initials': _initials(a['name'])})
                elif needs_ride and not ride_with:
                    unclaimed_riders.append(a)
        except Exception as e:
            app.logger.error(f"carpool processing failed: {e}")
            return render_template('errors/500.html', error=str(e)), 500

        # Weather: opt-in via adventure['show_weather']. Cache for 6h in the
        # DB; refetch on miss. Every failure -> None so the page never 500s
        # because of weather. See docs/weather-and-multiday-research.md §5,6.
        weather = None
        weather_days = []
        weather_lat = adventure['latitude']
        weather_lon = adventure['longitude']
        weather_available = False
        weather_not_available = False
        # Compute the event window once. For single-day events, end_date is
        # None; for multi-day, it's the last day of the event. get_weather()
        # pads short events out to ~6 display days; we keep the whole padded
        # window for the strip and the event day for the hero.
        adventure_end_date = None
        try:
            if 'end_date' in adventure.keys() and adventure['end_date']:
                adventure_end_date = adventure['end_date']
        except (KeyError, AttributeError):
            adventure_end_date = None

        try:
            if adventure['show_weather'] and adventure['date']:
                cached = adventure['weather_json']
                cached_at = adventure['weather_fetched_at']
                if cached and cached_at:
                    try:
                        age = datetime.utcnow() - datetime.fromisoformat(cached_at)
                        if age.total_seconds() < 6 * 3600:
                            cached_list = json.loads(cached)
                    except (ValueError, TypeError):
                        pass
                if weather is None:
                    fresh = get_weather(adventure['location'], adventure['date'], adventure_end_date)
                    if fresh:
                        weather_available = bool(fresh.get('available'))
                        weather_not_available = fresh.get('available') is False
                        # target = the adventure date's row; fallback to last available.
                        target = next((d for d in fresh['days'] if d.get('date') == adventure['date']), None)
                        if target is None and fresh['days']:
                            target = fresh['days'][-1]
                        weather = target
                        weather_days = fresh['days']
                        weather_lat = fresh.get('lat')
                        weather_lon = fresh.get('lon')
                        try:
                            save_weather(adventure['id'], json.dumps(fresh['days']),
                                         latitude=weather_lat, longitude=weather_lon)
                        except Exception as e:
                            app.logger.warning(f'save_weather failed: {e}')
        except Exception as e:
            app.logger.error(f"weather fetch failed: {e}")
            # weather stays as defaults (None, [], False, False)
        except Exception as e:
            app.logger.error(f"weather fetch failed: {e}")
            return render_template('errors/500.html', error=str(e)), 500


        # Soft-deleted: show the deleted-state page; the shared link stays
        # loadable so someone opening it can see what happened and undo.
        try:
            deleted_at = adventure['deleted_at'] if 'deleted_at' in adventure.keys() else None
        except (KeyError, AttributeError, IndexError):
            deleted_at = None
        if deleted_at:
            return render_template('adventure_deleted.html',
                                   adventure=adventure,
                                   share_url=(request.url_root.rstrip('/')
                                              + url_for('view_adventure', share_id=share_id)))

        attendees = get_attendees(adventure['id'])
        going_count = get_going_count(adventure['id'])
        my_rsvp = get_attendee_by_token(adventure['id'], request.cookies.get(RSVP_COOKIE))
        name_map = disambiguate_name_map(attendees)

        # F5 carpool: group attendees into drivers + unclaimed riders for the card.
        drivers = []
        unclaimed_riders = []
        for a in attendees:
            if a['status'] != 'going':
                continue
            # Safe access across all 3 row types
            try:
                driving = 1 if a['driving'] else 0
                needs_ride = 1 if a['needs_ride'] else 0
                ride_with = a['ride_with_driver_id'] if 'ride_with_driver_id' in a.keys() else None
            except (KeyError, AttributeError, IndexError):
                driving, needs_ride, ride_with = 0, 0, None
            if driving:
                riders = [
                    r for r in attendees
                    if r['status'] == 'going'
                    and ('needs_ride' in r.keys() and r['needs_ride'])
                    and ('ride_with_driver_id' in r.keys() and r['ride_with_driver_id'] == a['id'])
                ]
                drivers.append({**dict(a), 'riders': riders,
                                'initials': _initials(a['name'])})
            elif needs_ride and not ride_with:
                unclaimed_riders.append(a)

        carpool_summary = get_carpool_summary(adventure['id'])

        # Weather: opt-in via adventure['show_weather']. Cache for 6h in the
        # DB; refetch on miss. Every failure -> None so the page never 500s
        # because of weather. See docs/weather-and-multiday-research.md §5,6.
        weather = None
        weather_days = []
        weather_lat = adventure['latitude']
        weather_lon = adventure['longitude']
        weather_available = False
        weather_not_available = False
        # Compute the event window once. For single-day events, end_date is
        # None; for multi-day, it's the last day of the event. get_weather()
        # pads short events out to ~6 display days; we keep the whole padded
        # window for the strip and the event day for the hero.
        adventure_end_date = None
        try:
            if 'end_date' in adventure.keys() and adventure['end_date']:
                adventure_end_date = adventure['end_date']
        except (KeyError, AttributeError):
            adventure_end_date = None

        def _cache_covers_window(day_list):
            """True only if the cached list actually reaches the event's last
            day. A cached single-day fetch left over after an event was made
            multi-day would otherwise render 1 day forever (until the 6h TTL
            expires) — treat that as a miss so we refetch the full window."""
            if not day_list:
                return False
            if not adventure_end_date:
                # Single-day: cache is fine if it holds the target day.
                return any(d.get('date') == adventure['date'] for d in day_list)
            # Multi-day: the cache must cover through the event's end day.
            return any(d.get('date') == adventure_end_date for d in day_list)

        try:
            if adventure['show_weather'] and adventure['date']:
                cached = adventure['weather_json']
                cached_at = adventure['weather_fetched_at']
                if cached and cached_at:
                    try:
                        age = datetime.utcnow() - datetime.fromisoformat(cached_at)
                        if age.total_seconds() < 6 * 3600:
                            cached_list = json.loads(cached)
                            # The cache holds the padded display window
                            # (get_weather returned it). Use it as-is; pick the
                            # target day's row for the hero default.
                            if isinstance(cached_list, list) and _cache_covers_window(cached_list):
                                windowed = cached_list
                                if windowed:
                                    weather = next((d for d in windowed if d.get('date') == adventure['date']), windowed[0] if windowed else None)
                                    weather_days = windowed
                                    weather_available = True
                    except (ValueError, TypeError):
                        pass
                if weather is None:
                    fresh = get_weather(adventure['location'], adventure['date'], adventure_end_date)
                    if fresh:
                        weather_available = bool(fresh.get('available'))
                        weather_not_available = fresh.get('available') is False
                        # target = the adventure date's row; fallback to last available.
                        target = next((d for d in fresh['days'] if d.get('date') == adventure['date']), None)
                        if target is None and fresh['days']:
                            target = fresh['days'][-1]
                        weather = target
                        weather_days = fresh['days']
                        weather_lat = fresh.get('lat')
                        weather_lon = fresh.get('lon')
                        try:
                            save_weather(adventure['id'], json.dumps(fresh['days']),
                                         latitude=weather_lat, longitude=weather_lon)
                        except Exception as e:
                            app.logger.warning('save_weather failed: %s', e)
        except Exception as e:
            app.logger.warning('weather block failed: %s', e)
            weather = None
            weather_days = []
            weather_available = False
            weather_not_available = False

        # Multi-day weather summary line: one sentence covering the whole trip
        # ("3-day trip · high 84 / low 55 · rain Thu"), shown only when the event
        # actually spans >1 day. Uses the event days (in_event=True), never the
        # padded context days around them that the strip shows.
        weather_summary = ''
        if weather_days and adventure_end_date:
            event_days = [d for d in weather_days if d.get('in_event')]
            if len(event_days) > 1:
                highs = [d['high_f'] for d in event_days if d.get('high_f') is not None]
                lows = [d['low_f'] for d in event_days if d.get('low_f') is not None]
                rainy = [d for d in event_days
                         if d.get('rain_pct') and d['rain_pct'] > 20]
                parts = [f"{len(event_days)}-day trip"]
                if highs:
                    parts.append(f"high {max(highs)}\u00b0")
                if lows:
                    parts.append(f"low {min(lows)}\u00b0")
                if rainy:
                    parts.append(f"rain {rainy[0].get('day_label') or ''}")
                weather_summary = ' \u00b7 '.join(parts)

        share_url = request.url_root.rstrip('/') + url_for('view_adventure', share_id=share_id)
        og_image_url = request.url_root.rstrip('/') + url_for('og_image', share_id=share_id)

        # Cost breakdown line items (+ running total) for the cost card.
        cost_items = get_cost_items(adventure['id'])
        cost_total = get_cost_item_total(adventure['id'])

        # Cost splits: server-render the card once here (fragments after each
        # action reuse the same partial via _render_splits_fragment). Opt-in per
        # adventure (host checks "Split costs with Venmo" in the form) — default
        # off so board-game nights don't show money math they don't need.
        show_splits = _adventure_flag(adventure, 'show_splits')
        splits_card = _render_splits_fragment(adventure) if show_splits else ''

        # Group packing board: server-render the gear card once here (fragments
        # after each action reuse the same partial via _render_packing_fragment).
        # Opt-in per adventure (host checks "Group gear") — default off.
        show_packing = _adventure_flag(adventure, 'show_gear')
        packing_card = _render_packing_fragment(adventure, my_rsvp) if show_packing else ''

        # Series: if this adventure is part of a recurring series, grab sibling
        # occurrences for a "part of a series" strip on the page.
        series = []
        series_id = adventure['series_id'] if 'series_id' in adventure.keys() else None
        if series_id:
            series = [s for s in get_series(series_id) if s['share_id'] != share_id]

        return render_template('adventure.html',
                               adventure=adventure,
                               attendees=attendees,
                               name_map=name_map,
                               going_count=going_count,
                               my_rsvp=my_rsvp,
                               share_url=share_url,
                               og_image_url=og_image_url,
                               weather=weather,
                               weather_days=weather_days,
                               weather_available=weather_available,
                               weather_not_available=weather_not_available,
                               weather_lat=weather_lat,
                               weather_lon=weather_lon,
                               weather_summary=weather_summary,
                               # F5 carpool: drivers list (each with claimed riders), unclaimed riders, summary
                               drivers=drivers,
                               unclaimed_riders=unclaimed_riders,
                               carpool_summary=carpool_summary,
                               # cost breakdown card
                               cost_items=cost_items,
                               cost_total=cost_total,
                               # cost splits card
                               splits_card=splits_card,
                               show_splits=show_splits,
                               # group packing board
                               packing_card=packing_card,
                               show_packing=show_packing,
                               # series siblings for recurring events
                               series=series,
                               # end_date / end_time for multi-day display. Safe access
                               # across all 3 row types (sqlite3.Row, _DictRow, turso_serverless).
                               end_date=(adventure['end_date'] if 'end_date' in adventure.keys() else None),
                               end_time=(adventure['end_time'] if 'end_time' in adventure.keys() else None),
                               # Friendly category label for the cover eyebrow. Old rows
                               # can hold pre-rename ids, so fall back to the raw id.
                               vibe_label=(VIBE_LABELS.get(adventure['vibe'], adventure['vibe']) or ''),
                               google_cal_url=_google_calendar_url(adventure, share_url),
                                # Days until event countdown (for multi-day, use start date).
                                days_until=(lambda d: (datetime.strptime(d, '%Y-%m-%d').date() - mountain_today()).days)(adventure['date'])
                                if adventure['date'] else None,)

    @app.route('/adventure/<share_id>/edit', methods=['GET', 'POST'])
    def edit_adventure(share_id):
        adventure = get_adventure_by_share_id(share_id)
        if not adventure:
            return render_template('errors/404.html'), 404

        form_context = {
            'form_action': url_for('edit_adventure', share_id=share_id),
            'submit_label': 'Save Changes',
            'cancel_url': url_for('view_adventure', share_id=share_id),
        }

        if request.method == 'POST':
            name = request.form.get('name', '').strip()
            date = request.form.get('date', '').strip()
            time = request.form.get('time', '').strip()
            location = request.form.get('location', '').strip()
            description = request.form.get('description', '').strip()
            packing_list = request.form.get('packing_list', '').strip()
            carpool = 1 if request.form.get('carpool') else 0
            tagline = request.form.get('tagline', '').strip()
            show_weather = 1 if request.form.get('show_weather') else 0
            show_splits = 1 if request.form.get('show_splits') else 0
            show_gear = 1 if request.form.get('show_gear') else 0
            end_date = request.form.get('end_date', '').strip() or None
            end_time = request.form.get('end_time', '').strip() or None
            cost = form_cost_or_none()
            vibe = request.form.get('vibe', '').strip()
            if vibe not in VIBE_IDS:
                vibe = ''
            cover_image = request.form.get('cover_image', '').strip() or None

            errors = validate_adventure_form(name, date, time, location, description, packing_list, tagline, end_date, end_time)
            if errors:
                for error in errors:
                    flash(error, 'error')
                return render_template('edit.html',
                                       adventure=adventure,
                                       name=name, date=date, time=time,
                                       location=location, description=description,
                                       packing_list=packing_list,
                                       carpool=carpool,
                                       tagline=tagline,
                                       show_weather=show_weather,
                                       show_splits=show_splits,
                                       show_gear=show_gear,
                                       end_date=end_date, end_time=end_time,
                                       cost=cost,
                                       vibe=vibe,
                                       vibes=VIBES, vibe_groups=VIBE_GROUPS,
                                       **form_context), 400

            # Single write = single Turso push (the old two-call path opened two
            # connections and pushed twice, making save ~2x slower). Also clears
            # cached weather so a date/location fix refetches on the next view.
            update_adventure_clearing_weather(adventure['id'], name, date, time, location, description, packing_list, carpool, tagline, show_weather, end_date, end_time, vibe, cost, show_splits=show_splits, show_gear=show_gear, cover_image=cover_image)
            flash('Adventure updated!', 'success')
            return redirect(url_for('view_adventure', share_id=share_id))

        # GET: pre-fill the form from the existing adventure
        return render_template('edit.html',
                               adventure=adventure,
                               name=adventure['name'],
                               date=adventure['date'],
                               time=adventure['time'] or '',
                               location=adventure['location'],
                               description=adventure['description'] or '',
                               packing_list=adventure['packing_list'] or '',
                               carpool=adventure['carpool'],
                               tagline=adventure['tagline'] or '',
                               # show_weather is from the weather migration; bracket access
                               # + try/except handles the 3 row types (sqlite3.Row has no
                               # .get(), turso_serverless rows have no .get(), _DictRow does).
                               show_weather=(lambda: (lambda v: 1 if v is None else v)(adventure['show_weather'] if 'show_weather' in adventure.keys() else 1))(),
                               end_date=adventure['end_date'] if 'end_date' in adventure.keys() else None,
                               end_time=adventure['end_time'] if 'end_time' in adventure.keys() else None,
                               cost=adventure['cost'] if 'cost' in adventure.keys() else '',
                               vibe=adventure['vibe'] or '',
                               show_splits=(lambda: (lambda v: 0 if v is None else v)(adventure['show_splits'] if 'show_splits' in adventure.keys() else 0))(),
                               show_gear=(lambda: (lambda v: 0 if v is None else v)(adventure['show_gear'] if 'show_gear' in adventure.keys() else 0))(),
                               cover_image=adventure['cover_image'] if 'cover_image' in adventure.keys() else '',
                               vibes=VIBES, vibe_groups=VIBE_GROUPS,
                               **form_context)

    @app.route('/adventure/<share_id>/delete', methods=['POST'])
    def delete_adventure_route(share_id):
        # Soft-delete: the adventure is clocked with deleted_at so it can be
        # undone for a window. Opening the shared link shows the deleted state
        # with an undo button. Must find deleted + live rows to avoid undoing
        # an already-404'd adventure at the wrong time.
        adventure = get_adventure_by_share_id(share_id, include_deleted=True)
        if not adventure:
            return render_template('errors/404.html'), 404

        delete_adventure(adventure['id'])
        flash('Adventure deleted. You can undo from its page.', 'success')
        return redirect(url_for('view_adventure', share_id=share_id))

    @app.route('/adventure/<share_id>/undo', methods=['POST'])
    def undo_adventure_route(share_id):
        """Restore a soft-deleted adventure within its undo window."""
        adventure = get_adventure_by_share_id(share_id, include_deleted=True)
        if not adventure:
            return render_template('errors/404.html'), 404
        try:
            deleted_at = adventure['deleted_at'] if 'deleted_at' in adventure.keys() else None
        except (KeyError, AttributeError, IndexError):
            deleted_at = None
        if not deleted_at:
            flash('This adventure was not deleted.', 'error')
        else:
            undo_delete(adventure['id'])
            flash('Adventure restored!', 'success')
        return redirect(url_for('view_adventure', share_id=share_id))

    @app.route('/adventure/<share_id>/series/edit-future', methods=['GET', 'POST'])
    def edit_series_future(share_id):
        """Edit every future occurrence of a recurring series at once.

        Re-uses the standard _adventure_form.html partial for the GET so the
        UI is identical to editing a single adventure. On POST, only the
        shared fields (location, time, vibe, description, packing, carpool,
        weather, tagline, cost) are written — date and end_date are kept
        per-occurrence (they're what makes each row distinct). Past occurrences
        are not touched.
        """
        adventure = get_adventure_by_share_id(share_id)
        if not adventure:
            return render_template('errors/404.html'), 404
        try:
            series_id = adventure['series_id'] if 'series_id' in adventure.keys() else None
        except (KeyError, AttributeError, IndexError):
            series_id = None
        if not series_id:
            flash('This adventure is not part of a series.', 'error')
            return redirect(url_for('view_adventure', share_id=share_id))

        future_count = count_future_series_occurrences(series_id, adventure['date'])

        if request.method == 'POST':
            name = request.form.get('name', '').strip() or adventure['name']
            time = request.form.get('time', '').strip() or None
            location = request.form.get('location', '').strip() or adventure['location']
            description = request.form.get('description', '').strip()
            packing_list = request.form.get('packing_list', '').strip()
            carpool = 1 if request.form.get('carpool') else 0
            tagline = request.form.get('tagline', '').strip()
            show_weather = 1 if request.form.get('show_weather') else 0
            show_splits = 1 if request.form.get('show_splits') else 0
            show_gear = 1 if request.form.get('show_gear') else 0
            end_time = request.form.get('end_time', '').strip() or None
            vibe = request.form.get('vibe', '').strip()
            if vibe not in VIBE_IDS:
                vibe = adventure['vibe'] or ''
            cost = form_cost_or_none()

            n = update_future_series_occurrences(
                series_id, adventure['date'],
                name=name, time=time, location=location, description=description,
                packing_list=packing_list, carpool=carpool, tagline=tagline,
                show_weather=show_weather, end_time=end_time, vibe=vibe, cost=cost,
                show_splits=show_splits, show_gear=show_gear,
            )
            flash(f'Updated {n} future occurrence{"s" if n != 1 else ""}.', 'success')
            return redirect(url_for('view_adventure', share_id=share_id))

        # GET: pre-fill from this occurrence; pass through to the same form partial.
        return render_template('edit.html',
                               adventure=adventure,
                               name=adventure['name'],
                               date=adventure['date'],
                               time=adventure['time'] or '',
                               location=adventure['location'],
                               description=adventure['description'] or '',
                               packing_list=adventure['packing_list'] or '',
                               carpool=adventure['carpool'],
                               tagline=adventure['tagline'] or '',
                               show_weather=(adventure['show_weather'] if 'show_weather' in adventure.keys() and adventure['show_weather'] is not None else 1),
                               show_splits=(adventure['show_splits'] if 'show_splits' in adventure.keys() and adventure['show_splits'] is not None else 0),
                               show_gear=(adventure['show_gear'] if 'show_gear' in adventure.keys() and adventure['show_gear'] is not None else 0),
                               end_date=None,  # end_date is per-occurrence, not editable here
                               end_time=adventure['end_time'] if 'end_time' in adventure.keys() else None,
                               cost=adventure['cost'] if 'cost' in adventure.keys() else '',
                               vibe=adventure['vibe'] or '',
                               vibes=VIBES, vibe_groups=VIBE_GROUPS,
                               form_action=url_for('edit_series_future', share_id=share_id),
                               submit_label=f'Save for all {future_count} future occurrence{"s" if future_count != 1 else ""}',
                               cancel_url=url_for('view_adventure', share_id=share_id),
                               series_mode=True,
                               future_count=future_count)

    @app.route('/adventure/<share_id>/series/cancel', methods=['POST'])
    def cancel_series_future(share_id):
        """Soft-delete every future occurrence of a recurring series at once.
        Each row keeps its 24h-undo window, so a mis-click is recoverable per
        the existing per-adventure undo button."""
        adventure = get_adventure_by_share_id(share_id)
        if not adventure:
            return render_template('errors/404.html'), 404
        try:
            series_id = adventure['series_id'] if 'series_id' in adventure.keys() else None
        except (KeyError, AttributeError, IndexError):
            series_id = None
        if not series_id:
            flash('This adventure is not part of a series.', 'error')
            return redirect(url_for('view_adventure', share_id=share_id))

        n = soft_delete_future_series_occurrences(series_id, adventure['date'])
        if n > 0:
            flash(f'Cancelled {n} future occurrence{"s" if n != 1 else ""}. Undo from any of their pages within 24h.', 'success')
        else:
            flash('No future occurrences to cancel.', 'error')
        return redirect(url_for('view_adventure', share_id=share_id))


    @app.route('/adventure/<share_id>/rsvp', methods=['POST'])
    def rsvp(share_id):
        adventure = get_adventure_by_share_id(share_id)
        if not adventure:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'error': 'Not found'}), 404
            return render_template('errors/404.html'), 404

        name = request.form.get('name', '').strip()
        plus_one_name = request.form.get('plus_one_name', '').strip()
        status = request.form.get('status', 'going')
        token = request.cookies.get(RSVP_COOKIE)

        # A browser we recognize (cookie token matches) can flip their status
        # without retyping their name.
        mine = get_attendee_by_token(adventure['id'], token)
        if not name and mine:
            name = mine['name']

        if not name:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'error': 'Name is required'}), 400
            flash('Name is required', 'error')
            return redirect(url_for('view_adventure', share_id=share_id))

        if len(name) > 100:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'error': 'Name too long'}), 400
            flash('Name must be 100 characters or less', 'error')
            return redirect(url_for('view_adventure', share_id=share_id))

        if plus_one_name and len(plus_one_name) > 100:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'error': 'Plus-one name too long'}), 400
            flash('Plus-one name must be 100 characters or less', 'error')
            return redirect(url_for('view_adventure', share_id=share_id))

        if status not in ('going', 'interested', 'cant'):
            status = 'going'

        # Re-clicking the status you're already on = update in place.
        # Previously this deleted the attendee, but that's surprising UX —
        # clicking your current status should just refresh/save changes
        # (like adding or editing a +1 name), not remove you entirely.
        # To leave the event, change to "Interested" or "Can't Go" instead.
        if mine and status == mine['status']:
            # Fall through to add_attendee() which updates in place
            pass

        # Only "Going" people can (or need to) volunteer to drive. The checkbox
        # is ignored for any other status.
        driving = 1 if (status == 'going' and request.form.get('driving')) else 0

        # F5 carpool fields (only meaningful for going attendees; ignored otherwise).
        seats_raw = request.form.get('seats', '').strip()
        seats = int(seats_raw) if seats_raw.isdigit() and 1 <= int(seats_raw) <= 15 else None
        departure_time = request.form.get('departure_time', '').strip() or None
        departure_location = request.form.get('departure_location', '').strip() or None
        needs_ride = 1 if (status == 'going' and request.form.get('needs_ride')) else 0
        # If "I'm driving" is on, force needs_ride off (a driver doesn't need a ride).
        if driving:
            needs_ride = 0

        try:
            my_token = add_attendee(adventure['id'], name, status, token=token,
                                    driving=driving,
                                    seats=seats,
                                    departure_time=departure_time,
                                    departure_location=departure_location,
                                    needs_ride=needs_ride,
                                    plus_one_name=plus_one_name)
        except Exception as e:
            app.logger.error('RSVP add_attendee failed: %s', e, exc_info=True)
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'error': f'Database write failed: {str(e)}'}), 500
            flash(f'Database write failed: {str(e)}', 'error')
            return redirect(url_for('view_adventure', share_id=share_id))

        # Re-read so the response reflects whatever just changed.
        attendees = get_attendees(adventure['id'])
        going_count = get_going_count(adventure['id'])

        resp = None
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            # Re-read current user's attendee row so the carpool fragment renders
            # the right "your car" / "pick a driver" affordances for this browser.
            mine = get_attendee_by_token(adventure['id'], my_token)
            resp = jsonify({
                'going_count': going_count,
                'attendees': [{
                    'name': a['name'],
                    'status': a['status'],
                    'plus_one_name': a['plus_one_name'] if 'plus_one_name' in a.keys() else None,
                    'driving': 1 if a['driving'] else 0,
                    'needs_ride': 1 if a['needs_ride'] else 0,
                    'seats': a['seats'] if 'seats' in a.keys() else None,
                    'departure_time': a['departure_time'] if 'departure_time' in a.keys() else None,
                    'departure_location': a['departure_location'] if 'departure_location' in a.keys() else None,
                } for a in attendees],
                'my_status': status,
                'carpool_html': _render_carpool_fragment(adventure, mine),
            })
        else:
            resp = make_response(redirect(url_for('view_adventure', share_id=share_id)))
            flash('RSVP saved!', 'success')

        # Drop the token cookie on the response so the browser remembers who it is.
        resp.set_cookie(RSVP_COOKIE, my_token, max_age=RSVP_COOKIE_MAX_AGE,
                        httponly=True, samesite='Lax', secure=True)
        return resp

    @app.route('/adventure/<share_id>/attendee/<int:attendee_id>/delete', methods=['POST'])
    def delete_attendee_route(share_id, attendee_id):
        """Hard-delete a single attendee (RSVP or status row) from an adventure.

        Link-trusted, no-auth app — anyone holding the shared link may remove
        an attendee. This lets the host clear a stray test RSVP before launch. Deleting
        the attendee also removes their carpool associations (the row itself
        is gone, so ride_with references to it naturally drop).
        """
        adventure = get_adventure_by_share_id(share_id)
        if not adventure:
            return render_template('errors/404.html'), 404

        deleted = delete_attendee(adventure['id'], attendee_id)
        if not deleted:
            flash('That RSVP could not be found.', 'error')
            return redirect(url_for('view_adventure', share_id=share_id))

        flash('RSVP removed.', 'success')
        return redirect(url_for('view_adventure', share_id=share_id))

    def _build_carpool_data(adventure_id):
        """Group attendees into drivers (with riders) and unclaimed riders.

        Returns {drivers, unclaimed_riders, summary} matching the structure
        the carpool card template uses, so the JS can rebuild the card.
        """
        attendees = get_attendees(adventure_id)
        drivers = []
        unclaimed_riders = []
        for a in attendees:
            try:
                driving = 1 if a['driving'] else 0
                needs_ride = 1 if a['needs_ride'] else 0
                ride_with = a['ride_with_driver_id'] if 'ride_with_driver_id' in a.keys() else None
            except (KeyError, AttributeError, IndexError):
                driving, needs_ride, ride_with = 0, 0, None
            if driving:
                riders = [
                    {'id': r['id'], 'name': r['name']}
                    for r in attendees
                    if r['status'] == 'going'
                    and ('ride_with_driver_id' in r.keys() and r['ride_with_driver_id'] == a['id'])
                ]
                drivers.append({
                    'id': a['id'],
                    'name': a['name'],
                    'seats': a['seats'] if 'seats' in a.keys() else None,
                    'departure_time': a['departure_time'] if 'departure_time' in a.keys() else None,
                    'departure_location': a['departure_location'] if 'departure_location' in a.keys() else None,
                    'riders': riders,
                })
            elif needs_ride and not ride_with:
                unclaimed_riders.append({'id': a['id'], 'name': a['name']})

        summary = get_carpool_summary(adventure_id)
        return {'drivers': drivers, 'unclaimed_riders': unclaimed_riders, 'summary': summary}

    def _render_carpool_fragment(adventure, my_rsvp):
        """Server-render the carpool card HTML (single source of truth).

        Used on first page load (included by adventure.html) and returned as a
        fragment after every carpool action, so the browser never re-derives
        the markup and the card can't drift between template and JS.
        """
        data = _build_carpool_data(adventure['id'])
        return render_template(
            '_carpool_card.html',
            adventure=adventure,
            drivers=data['drivers'],
            unclaimed_riders=data['unclaimed_riders'],
            carpool_summary=data['summary'],
            my_rsvp=my_rsvp,
        )

    def _render_cost_fragment(adventure):
        """Server-render the cost breakdown card HTML (single source of truth)."""
        items = get_cost_items(adventure['id'])
        return render_template(
            '_cost_card.html',
            adventure=adventure,
            cost_items=items,
            cost_total=get_cost_item_total(adventure['id']),
        )

    def _render_splits_fragment(adventure):
        """Server-render the cost splits card HTML (single source of truth).
        Includes the expenses list, the equal-split balances, and a Venmo
        deeplink for each debtor -> creditor edge.
        """
        expenses = get_expenses(adventure['id'])
        splits = compute_splits(adventure['id'])
        # Attendees with their venmo_handle + splits opt-out for the inline
        # editor. Convert rows to plain dicts so templates can use .get() /
        # square-bracket access; the handle/splits columns may be absent on
        # older rows, so default them.
        attendees = []
        for a in get_attendees(adventure['id']):
            d = dict(a)
            d['venmo_handle'] = d.get('venmo_handle') or None
            d['splits'] = d.get('splits', 1)
            if d['splits'] is None:
                d['splits'] = 1
            attendees.append(d)
        return render_template(
            '_splits_card.html',
            adventure=adventure,
            expenses=expenses,
            splits=splits,
            attendees=attendees,
            name_map=disambiguate_name_map(attendees),
        )

    def _render_packing_fragment(adventure, my_rsvp=None):
        """Server-render the group packing list card (single source of truth).
        Includes the shared gear board with who's claimed each item, plus the
        Going roster so the claim dropdown lists the right people.

        `my_rsvp` is the current browser's attendee row (or None when they
        haven't RSVP'd). The card uses it for the one-tap "I'll bring it"
        button, so it must always be passed — the template dereferences
        `my_rsvp.id`.
        """
        items = get_packing_items(adventure['id'])
        attendees = [dict(a) for a in get_attendees(adventure['id'])]
        going_attendees = [a for a in attendees if a['status'] == 'going']
        if my_rsvp is None:
            my_rsvp = get_attendee_by_token(adventure['id'], request.cookies.get(RSVP_COOKIE))
        return render_template(
            '_packing_card.html',
            adventure=adventure,
            packing_items=items,
            going_attendees=going_attendees,
            attendees=attendees,
            my_rsvp=my_rsvp,
            name_map=disambiguate_name_map(attendees),
        )

    @app.route('/adventure/<share_id>/carpool', methods=['POST'])
    def carpool(share_id):
        """Handle carpool claim / unclaim actions.

        action: claim_rider | claim_driver | unclaim
        attendee_id: target attendee id (rider for claim_rider and unclaim,
                     driver for claim_driver)
        """
        adventure = get_adventure_by_share_id(share_id)
        if not adventure:
            return jsonify({'error': 'Not found'}), 404

        action_type = request.form.get('action', '')
        target_id_raw = request.form.get('attendee_id', '')
        if not target_id_raw.isdigit():
            return jsonify({'error': 'Invalid attendee'}), 400
        target_id = int(target_id_raw)

        token = request.cookies.get(RSVP_COOKIE)
        mine = get_attendee_by_token(adventure['id'], token) if token else None
        if not mine:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'error': 'You must RSVP first'}), 403
            flash('You must RSVP first', 'error')
            return redirect(url_for('view_adventure', share_id=share_id))

        ok, msg, flash_msg = True, None, None
        if action_type == 'claim_rider':
            ok, msg = claim_rider(adventure['id'], mine['id'], target_id)
            flash_msg = 'You added them to your car' if ok else (msg or 'Could not add rider')

        elif action_type == 'claim_driver':
            ok, msg = claim_driver(adventure['id'], mine['id'], target_id)
            if ok:
                driver_name = 'the driver'
                for a in get_attendees(adventure['id']):
                    if a['id'] == target_id:
                        driver_name = a['name']
                        break
                flash_msg = f"You're riding with {driver_name}"
            else:
                flash_msg = msg or 'Could not claim driver'

        elif action_type == 'unclaim':
            ok, msg = unclaim(adventure['id'], mine['id'], target_id)
            flash_msg = 'Removed from the car' if ok else (msg or 'Could not unclaim')

        else:
            ok = False
            flash_msg = 'Unknown action'

        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        if not ok and not is_ajax:
            flash(flash_msg, 'error')

        if is_ajax:
            return jsonify({
                'ok': ok,
                'flash': flash_msg,
                'html': _render_carpool_fragment(adventure, mine),
            })
        return redirect(url_for('view_adventure', share_id=share_id))

    @app.route('/adventure/<share_id>/carpool_creator', methods=['POST'])
    def carpool_creator(share_id):
        """Carpool management actions.

        Anyone with the link can manage the carpool (the link is the
        permission on this no-auth app). Each action still validates its
        targets server-side (attendees must be going, targets must be drivers,
        etc.).

        Actions:
          - move_rider: move a rider to a different driver's car
          - edit_driver: update a driver's seats, departure_time,
                         departure_location
        """
        adventure = get_adventure_by_share_id(share_id)
        if not adventure:
            return jsonify({'error': 'Not found'}), 404

        action_type = request.form.get('action', '')
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

        if action_type == 'move_rider':
            rider_id_raw = request.form.get('rider_id', '')
            driver_id_raw = request.form.get('driver_id', '')
            if not rider_id_raw.isdigit() or not driver_id_raw.isdigit():
                ok, msg = False, 'Invalid attendee id'
            else:
                ok, msg = move_rider(int(rider_id_raw), int(driver_id_raw))

        elif action_type == 'edit_driver':
            driver_id_raw = request.form.get('driver_id', '')
            if not driver_id_raw.isdigit():
                ok, msg = False, 'Invalid driver id'
            else:
                driver_id = int(driver_id_raw)
                seats_raw = request.form.get('seats', '').strip()
                seats = int(seats_raw) if seats_raw.isdigit() and 1 <= int(seats_raw) <= 15 else None
                departure_time = request.form.get('departure_time', '').strip() or None
                departure_location = request.form.get('departure_location', '').strip() or None
                update_attendee(driver_id,
                    seats=seats,
                    departure_time=departure_time,
                    departure_location=departure_location)
                ok, msg = True, None

        else:
            ok, msg = False, 'Unknown action'

        flash_msg = msg if not ok else ('Rider moved' if action_type == 'move_rider'
                  else 'Driver updated' if action_type == 'edit_driver'
                  else 'Done')
        if not ok and not is_ajax:
            flash(flash_msg, 'error')

        if is_ajax:
            mine = get_attendee_by_token(adventure['id'], request.cookies.get(RSVP_COOKIE))
            return jsonify({
                'ok': ok,
                'flash': flash_msg,
                'html': _render_carpool_fragment(adventure, mine),
            })
        return redirect(url_for('view_adventure', share_id=share_id))

    @app.route('/adventure/<share_id>/cost/add', methods=['POST'])
    def cost_add(share_id):
        """Add a cost breakdown line item. Anyone with the link can add, mirroring
        the carpool trust model."""
        adventure = get_adventure_by_share_id(share_id)
        if not adventure:
            return jsonify({'error': 'Not found'}), 404
        label = request.form.get('label', '').strip() or request.form.get('name', '').strip()
        amount = request.form.get('amount', '').strip()
        if not label or not amount:
            return jsonify({'error': 'Both a name and amount are needed'}), 400
        if len(label) > 200 or len(amount) > 100:
            return jsonify({'error': 'Keep name and amount short'}), 400
        add_cost_item(adventure['id'], label, amount)
        return jsonify({
            'ok': True,
            'flash': 'Added',
            'html': _render_cost_fragment(adventure),
        })

    @app.route('/adventure/<share_id>/cost/<int:item_id>/delete', methods=['POST'])
    def cost_delete(share_id, item_id):
        """Delete a cost breakdown line item. Anyone with the link can delete."""
        adventure = get_adventure_by_share_id(share_id)
        if not adventure:
            return jsonify({'error': 'Not found'}), 404
        ok = delete_cost_item(adventure['id'], item_id)
        return jsonify({
            'ok': ok,
            'flash': 'Removed' if ok else 'Could not find that item',
            'html': _render_cost_fragment(adventure),
        })

    @app.route('/adventure/<share_id>/expense/add', methods=['POST'])
    def expense_add(share_id):
        """Add a cost-split expense (e.g. 'Eric paid $40 for groceries').
        Anyone with the link can add (matches the cost breakdown trust model)."""
        adventure = get_adventure_by_share_id(share_id)
        if not adventure:
            return jsonify({'error': 'Not found'}), 404
        if not _adventure_flag(adventure, 'show_splits'):
            return jsonify({'error': 'Splits are off for this adventure'}), 400
        paid_by_raw = request.form.get('paid_by', '').strip()
        label = request.form.get('label', '').strip()
        amount = request.form.get('amount', '').strip()
        if not paid_by_raw.isdigit():
            return jsonify({'error': 'Pick who paid'}), 400
        if not label or not amount:
            return jsonify({'error': 'Add a name and amount'}), 400
        if len(label) > 200 or len(amount) > 100:
            return jsonify({'error': 'Keep name and amount short'}), 400
        # Verify the payer belongs to this adventure
        paid_by_id = int(paid_by_raw)
        payer = next((a for a in get_attendees(adventure['id']) if a['id'] == paid_by_id), None)
        if not payer:
            return jsonify({'error': 'That person is not on this adventure'}), 400
        add_expense(adventure['id'], paid_by_id, label, amount)
        return jsonify({
            'ok': True,
            'flash': 'Added',
            'html': _render_splits_fragment(adventure),
        })

    @app.route('/adventure/<share_id>/expense/<int:expense_id>/delete', methods=['POST'])
    def expense_delete(share_id, expense_id):
        """Delete a cost-split expense. Anyone with the link can delete."""
        adventure = get_adventure_by_share_id(share_id)
        if not adventure:
            return jsonify({'error': 'Not found'}), 404
        if not _adventure_flag(adventure, 'show_splits'):
            return jsonify({'error': 'Splits are off for this adventure'}), 400
        ok = delete_expense(adventure['id'], expense_id)
        return jsonify({
            'ok': ok,
            'flash': 'Removed' if ok else 'Could not find that expense',
            'html': _render_splits_fragment(adventure),
        })

    @app.route('/adventure/<share_id>/attendee/<int:attendee_id>/venmo', methods=['POST'])
    def attendee_venmo(share_id, attendee_id):
        """Save an attendee's Venmo handle. Anyone with the link can save
        (matches the carpool + cost breakdown trust model — you trust the
        people who have the link)."""
        adventure = get_adventure_by_share_id(share_id)
        if not adventure:
            return jsonify({'error': 'Not found'}), 404
        if not _adventure_flag(adventure, 'show_splits'):
            return jsonify({'error': 'Splits are off for this adventure'}), 400
        attendee = next((a for a in get_attendees(adventure['id']) if a['id'] == attendee_id), None)
        if not attendee:
            return jsonify({'error': 'Not found'}), 404
        handle = request.form.get('venmo', '').strip()
        if len(handle) > 100:
            return jsonify({'error': 'That handle is too long'}), 400
        set_attendee_venmo(attendee_id, handle)
        return jsonify({
            'ok': True,
            'flash': 'Saved',
            'html': _render_splits_fragment(adventure),
        })

    @app.route('/adventure/<share_id>/attendee/<int:attendee_id>/splits', methods=['POST'])
    def attendee_splits(share_id, attendee_id):
        """Toggle whether an attendee is in the equal-split math.
        Opting out means 'I'm not splitting this trip' (e.g. someone paid for
        their own Airbnb room)."""
        adventure = get_adventure_by_share_id(share_id)
        if not adventure:
            return jsonify({'error': 'Not found'}), 404
        if not _adventure_flag(adventure, 'show_splits'):
            return jsonify({'error': 'Splits are off for this adventure'}), 400
        attendee = next((a for a in get_attendees(adventure['id']) if a['id'] == attendee_id), None)
        if not attendee:
            return jsonify({'error': 'Not found'}), 404
        # Read current value to toggle (attendee is a row without .get()).
        try:
            cur = int(attendee['splits']) if 'splits' in attendee.keys() and attendee['splits'] is not None else 1
        except (TypeError, ValueError, KeyError, IndexError):
            cur = 1
        new_val = 0 if cur else 1
        set_attendee_splits(attendee_id, new_val)
        return jsonify({
            'ok': True,
            'flash': 'Out of the split' if new_val == 0 else 'In the split',
            'html': _render_splits_fragment(adventure),
        })

    @app.route('/adventure/<share_id>/packing/add', methods=['POST'])
    def packing_add(share_id):
        """Add a group gear item (e.g. 'Camping stove'). Anyone with the link
        can add — matches the carpool/cost/splits trust model."""
        adventure = get_adventure_by_share_id(share_id)
        if not adventure:
            return jsonify({'error': 'Not found'}), 404
        if not _adventure_flag(adventure, 'show_gear'):
            return jsonify({'error': 'Group gear is off for this adventure'}), 400
        label = request.form.get('label', '').strip()
        category = request.form.get('category', 'other').strip()
        valid_categories = ('appetizer', 'main', 'side', 'dessert', 'drinks', 'other')
        if category not in valid_categories:
            category = 'other'
        if not label:
            return jsonify({'error': 'Add what you want to bring'}), 400
        if len(label) > 200:
            return jsonify({'error': 'Keep it short'}), 400
        add_packing_item(adventure['id'], label, category=category)
        return jsonify({
            'ok': True,
            'flash': 'Added',
            'html': _render_packing_fragment(adventure),
        })

    @app.route('/adventure/<share_id>/packing/<int:item_id>/delete', methods=['POST'])
    def packing_delete(share_id, item_id):
        """Delete a group gear item. Anyone with the link can delete."""
        adventure = get_adventure_by_share_id(share_id)
        if not adventure:
            return jsonify({'error': 'Not found'}), 404
        if not _adventure_flag(adventure, 'show_gear'):
            return jsonify({'error': 'Group gear is off for this adventure'}), 400
        ok = delete_packing_item(adventure['id'], item_id)
        return jsonify({
            'ok': ok,
            'flash': 'Removed' if ok else 'Could not find that item',
            'html': _render_packing_fragment(adventure),
        })

    @app.route('/adventure/<share_id>/packing/<int:item_id>/claim', methods=['POST'])
    def packing_claim(share_id, item_id):
        """Claim a group gear item for an attendee ('I'll bring the stove')."""
        adventure = get_adventure_by_share_id(share_id)
        if not adventure:
            return jsonify({'error': 'Not found'}), 404
        if not _adventure_flag(adventure, 'show_gear'):
            return jsonify({'error': 'Group gear is off for this adventure'}), 400
        attendee_id = request.form.get('attendee_id', '').strip()
        if not attendee_id.isdigit():
            return jsonify({'error': 'Pick who is bringing it'}), 400
        attendee_id = int(attendee_id)
        # Any attendee on the adventure can be assigned gear (host may log
        # claims before everyone RSVPs 'Going').
        attendee = next((a for a in get_attendees(adventure['id'])
                         if a['id'] == attendee_id), None)
        if not attendee:
            return jsonify({'error': 'Pick someone on the RSVP list'}), 400
        ok = claim_packing_item(adventure['id'], item_id, attendee_id)
        return jsonify({
            'ok': ok,
            'flash': 'Claimed' if ok else 'Could not claim',
            'html': _render_packing_fragment(adventure),
        })

    @app.route('/adventure/<share_id>/packing/<int:item_id>/unclaim', methods=['POST'])
    def packing_unclaim(share_id, item_id):
        """Free an already-claimed group gear item (someone can no longer
        bring it, or claimed it by accident)."""
        adventure = get_adventure_by_share_id(share_id)
        if not adventure:
            return jsonify({'error': 'Not found'}), 404
        if not _adventure_flag(adventure, 'show_gear'):
            return jsonify({'error': 'Group gear is off for this adventure'}), 400
        ok = claim_packing_item(adventure['id'], item_id, None, unclaim=True)
        return jsonify({
            'ok': ok,
            'flash': 'Unclaimed' if ok else 'Could not unclaim',
            'html': _render_packing_fragment(adventure),
        })

    @app.route('/adventure/<share_id>/calendar.ics')
    def calendar_ics(share_id):
        adventure = get_adventure_by_share_id(share_id)
        if not adventure:
            return render_template('errors/404.html'), 404

        # Build iCal dates: YYYYMMDD and optional HHMMSS
        date_compact = adventure['date'].replace('-', '')
        time_compact = ''
        if adventure['time']:
            time_compact = adventure['time'].replace(':', '') + '00'

        start = date_compact + 'T' + (time_compact or '000000')
        # DTEND: multi-day uses end_date (and end_time if set, else end-of-day);
        # single-day falls back to +1h (with time) or +1 day (all-day).
        # Use bracket access + try/except because sqlite3.Row has no .get();
        # _DictRow does. New columns may not exist on rows from pre-migration
        # backends, so we fall back to None.
        end_date_val = None
        end_time_val = None
        try:
            end_date_val = adventure['end_date']
            end_time_val = adventure['end_time']
        except (KeyError, IndexError):
            pass
        if end_date_val:
            end_date_compact = end_date_val.replace('-', '')
            end_time_compact = ''
            if end_time_val:
                end_time_compact = end_time_val.replace(':', '') + '00'
                end = end_date_compact + 'T' + end_time_compact
            else:
                # iCal DTEND is exclusive. For a multi-day event whose last day
                # is end_date, the end must be the start of the NEXT day
                # (end_date + 1 at 00:00) so calendars render every day of the
                # trip. Ending at 23:59 on end_date made apps compute the
                # duration as (end_date - start_date).days — one day short.
                end = (datetime.strptime(end_date_compact, '%Y%m%d')
                       + timedelta(days=1)).strftime('%Y%m%dT%H%M%S')
        else:
            start_dt = datetime.strptime(start, '%Y%m%dT%H%M%S')
            if time_compact:
                end_dt = start_dt + timedelta(hours=1)
            else:
                end_dt = start_dt + timedelta(days=1)
            end = end_dt.strftime('%Y%m%dT%H%M%S')

        uid = f"{adventure['share_id']}@adventure"

        lines = [
            'BEGIN:VCALENDAR',
            'VERSION:2.0',
            'PRODID:-//Adventure//EN',
            'BEGIN:VEVENT',
            f'UID:{uid}',
            f'DTSTAMP:{date_compact}T000000',
            f'DTSTART:{start}',
            f'DTEND:{end}',
            f'SUMMARY:{escape_ics(adventure["name"])}',
        ]
        if adventure['location']:
            lines.append(f'LOCATION:{escape_ics(adventure["location"])}')
        if adventure['description']:
            lines.append(f'DESCRIPTION:{escape_ics(adventure["description"])}')
        lines.append('END:VEVENT')
        lines.append('END:VCALENDAR')

        ics_content = '\r\n'.join(lines) + '\r\n'
        filename = f"adventure-{adventure['share_id']}.ics"
        return Response(
            ics_content,
            mimetype='text/calendar',
            # inline (not attachment) so phone browsers open the OS calendar
            # directly instead of showing a "download this file" prompt first.
            # iOS/Android treat an inline text/calendar response as an event to
            # add; a filename is included so desktop users can still save it.
            headers={'Content-Disposition': f'inline; filename="{filename}"'}
        )

    @app.errorhandler(404)
    def not_found(e):
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def server_error(e):
        return render_template('errors/500.html'), 500

    return app


app = create_app()
app.jinja_env.filters['format_date'] = format_date_filter
app.jinja_env.filters['day_name'] = day_name_filter
app.jinja_env.filters['day_short'] = day_short_filter
app.jinja_env.filters['month_day'] = month_day_filter
app.jinja_env.filters['month_abbr'] = month_abbr_filter
app.jinja_env.filters['day_num'] = day_num_filter
app.jinja_env.filters['format_time'] = format_time_filter
app.jinja_env.filters['display_cost'] = display_cost_filter
app.jinja_env.filters['venmo_deeplink'] = venmo_deeplink_filter

if __name__ == '__main__':
    # macOS reserves port 5000 for AirPlay, so default to 8080.
    app.run(debug=True, port=int(os.environ.get('PORT', '8080')))