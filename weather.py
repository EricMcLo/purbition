import json
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

# The app's trips happen in Mountain time, and the prod server runs in UTC.
# `date.today()` on prod is UTC, so "today" would roll over at 6pm Mountain —
# which silently drops a "before-event" day from the padded weather strip
# (6 -> 5 days) for events near today. Compute "today" in America/Denver so
# the pad is stable across that boundary on every host. Defined once here so
# get_weather() and anything else in this module agree.
def mountain_today():
    """Today's date (YYYY-MM-DD) in America/Denver, regardless of server tz."""
    return datetime.now(ZoneInfo('America/Denver')).date()

# Open-Meteo: no key, no billing, free under 10k calls/day for non-commercial.
# CC BY 4.0 attribution required (we display "Weather by Open-Meteo" in the card).
GEO_URL = 'https://geocoding-api.open-meteo.com/v1/search'
FORECAST_URL = 'https://api.open-meteo.com/v1/forecast'
NOMINATIM_URL = 'https://nominatim.openstreetmap.org/search'

# WMO weather codes -> plain words. We draw our own UI, so this is the only
# "styling" the API is allowed to do.
WMO = {
    0: 'Clear sky', 1: 'Mostly clear', 2: 'Partly cloudy', 3: 'Overcast',
    45: 'Fog', 48: 'Rime fog', 51: 'Light drizzle', 53: 'Drizzle',
    55: 'Heavy drizzle', 61: 'Light rain', 63: 'Rain', 65: 'Heavy rain',
    66: 'Freezing rain', 67: 'Freezing rain', 71: 'Light snow', 73: 'Snow',
    75: 'Heavy snow', 77: 'Snow grains', 80: 'Light rain showers',
    81: 'Rain showers', 82: 'Violent rain showers', 85: 'Snow showers',
    86: 'Heavy snow showers', 95: 'Thunderstorm', 96: 'Thunderstorm + hail',
    99: 'Thunderstorm + hail',
}

# User-Agent required by Nominatim usage policy (https://operations.osmfoundation.org/policies/nominatim/).
# Without it, Nominatim returns 403.
NOMINATIM_HEADERS = {'User-Agent': 'purbition/1.0 (https://purbition.com)'}


def _http_get_json(url, *, headers=None, timeout=4):
    """Fetch a URL and parse JSON. Returns None on any failure."""
    try:
        req = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except Exception:
        return None


def _geocode_open_meteo(location):
    """First geocode attempt: Open-Meteo's place-name index. Catches most named
    places (Moab, UT; Big Cottonwood Canyon; Brighton, UT). Fails on
    non-indexed names (e.g. Millcreek Canyon) and home addresses."""
    params = urllib.parse.urlencode({'name': location, 'count': 1, 'format': 'json'})
    data = _http_get_json(f'{GEO_URL}?{params}')
    if not data:
        return None
    hits = data.get('results') or []
    if not hits:
        return None
    return hits[0]['latitude'], hits[0]['longitude']


def _geocode_nominatim(location):
    """Fallback geocoder: OSM/Nominatim. Catches things Open-Meteo's index
    misses. Free under 1 req/sec courtesy limit; not perfect for every
    obscure trailhead, but combined with opt-in + fail-soft, missed
    geocodes just mean "no card," never "page error." """
    params = urllib.parse.urlencode({'q': location, 'format': 'json', 'limit': 1})
    data = _http_get_json(f'{NOMINATIM_URL}?{params}', headers=NOMINATIM_HEADERS)
    if not data:
        return None
    hits = data if isinstance(data, list) else []
    if not hits:
        return None
    try:
        lat = float(hits[0]['lat'])
        lon = float(hits[0]['lon'])
        return lat, lon
    except (KeyError, ValueError, TypeError):
        return None


def geocode(location):
    """Two-step geocoder: Open-Meteo first (faster, free, index of named
    places), Nominatim fallback (catches trailhead names Open-Meteo misses).
    Returns (lat, lon) or None."""
    coords = _geocode_open_meteo(location)
    if coords is not None:
        return coords
    return _geocode_nominatim(location)


def forecast(lat, lon, days):
    """Pull a daily forecast starting today, for `days` days. Returns a list
    of dicts (date, condition, high_f, low_f, rain_pct, wind_mph) or None."""
    params = urllib.parse.urlencode({
        'latitude': lat, 'longitude': lon,
        'daily': ('weather_code,temperature_2m_max,temperature_2m_min,'
                  'precipitation_probability_max,wind_speed_10m_max'),
        'temperature_unit': 'fahrenheit', 'wind_speed_unit': 'mph',
        'timezone': 'auto', 'forecast_days': min(days, 16),  # Open-Meteo caps at 16
    })
    data = _http_get_json(f'{FORECAST_URL}?{params}')
    if not data:
        return None
    daily = data.get('daily') or {}
    times = daily.get('time') or []
    if not times:
        return None
    rows = []
    for i, day_iso in enumerate(times):
        try:
            d = datetime.strptime(day_iso, '%Y-%m-%d')
            # Portable no-leading-zero day. `%-d` is BSD/Linux-only;
            # use slice + int() instead so it works on Windows too.
            day_label = f"{d.strftime('%a, %b ')}{int(day_iso[-2:])}"
        except ValueError:
            day_label = day_iso

        # Open-Meteo returns null for far-future temps; guard each value
        # before rounding so a missing temp never crashes the card.
        def _r(v):
            return round(v) if v is not None else None

        high_v = daily.get('temperature_2m_max', [None] * len(times))[i]
        low_v = daily.get('temperature_2m_min', [None] * len(times))[i]
        wind_v = daily.get('wind_speed_10m_max', [None] * len(times))[i]

        rows.append({
            'date': day_iso,
            'day_label': day_label,
            'condition': WMO.get(daily.get('weather_code', [None] * len(times))[i], 'Weather'),
            'high_f': _r(high_v),
            'low_f': _r(low_v),
            'rain_pct': daily.get('precipitation_probability_max', [0] * len(times))[i] or 0,
            'wind_mph': _r(wind_v),
        })
    return rows


def get_weather(location, date_iso, end_date_iso=None):
    """The one function the route calls. Returns a dict with lat/lon/days
    or None on any failure:

        {"lat": float, "lon": float, "location": str, "available": bool,
         "days": [{date, day_label, condition, high_f, low_f, rain_pct, wind_mph}, ...]}

    `end_date_iso` is the last day of the event (inclusive) for multi-day
    adventures. When set, we fetch enough forecast rows to cover the whole
    event window, then slice the result so the strip only shows the
    event's days — not the full 16-day forecast horizon. Single-day calls
    (end_date_iso is None) fetch through the target date only.

    `available=False` means the event is beyond Open-Meteo's 16-day forecast
    horizon, so no real forecast exists yet — the route renders a
    "Forecast not available yet" message instead of unrelated future days.
    Every hard failure (geocode miss, fetch error, parse error) returns None
    so the page never 500s because of weather.
    """
    try:
        target = datetime.strptime(date_iso, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None

    end_target = None
    if end_date_iso:
        try:
            end_target = datetime.strptime(end_date_iso, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            end_target = None

    today = mountain_today()
    days_out = (target - today).days
    if days_out < 0:
        return None

    # Last day we need a forecast for: target for single-day, end_target
    # (inclusive) for multi-day.
    last_event_day = end_target if (end_target and end_target > target) else target

    # Open-Meteo only forecasts today + 15 (16 rows). If the last event day
    # is beyond that, no real forecast exists yet — return a marker so the
    # template can say "not available yet" instead of showing the horizon's
    # unrelated days.
    if (last_event_day - today).days >= 16:
        return {"lat": None, "lon": None, "location": location,
                "available": False, "days": []}

    # Display window: pad short events out to MAX_DISPLAY_DAYS so the strip
    # fills the card instead of showing one lonely chip. Long events keep all
    # their days (the strip scrolls). Context days are tagged in_event=False
    # so the template can visually set them apart from the trip itself.
    MAX_DISPLAY_DAYS = 6
    event_days = (last_event_day - target).days + 1
    if event_days >= MAX_DISPLAY_DAYS:
        display_start, display_end = target, last_event_day
    else:
        pad = MAX_DISPLAY_DAYS - event_days
        before = pad // 2
        after = pad - before
        display_start = target - timedelta(days=before)
        display_end = last_event_day + timedelta(days=after)
        # Can't forecast the past: clamp start to today and give the lost
        # days back to the end if the end-still-start restriction demands it.
        if display_start < today:
            lost = (today - display_start).days
            display_start = today
            display_end += timedelta(days=lost)
        horizon = today + timedelta(days=15)
        if display_end > horizon:
            display_end = horizon

    # How many forecast rows we need: from today through the display window's
    # last day (inclusive).
    rows_needed = (display_end - today).days + 1

    coords = geocode(location)
    if coords is None:
        return None
    lat, lon = coords

    days = forecast(lat, lon, rows_needed)
    if not days:
        return None

    # Keep only the display window (today..horizon rows may overshoot when
    # the event is close to now) and tag which rows are the event itself.
    windowed = []
    for d in days:
        dd = datetime.strptime(d['date'], '%Y-%m-%d').date()
        if display_start <= dd <= display_end:
            d['in_event'] = target <= dd <= last_event_day
            windowed.append(d)

    return {"lat": lat, "lon": lon, "location": location, "available": True, "days": windowed}
