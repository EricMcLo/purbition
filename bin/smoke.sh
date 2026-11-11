#!/usr/bin/env bash
set -u
# Smoke test: curl the critical routes locally + on prod and report pass/fail.
#
# Usage: bin/smoke.sh  — or with LOCAL_URL/PROD_URL overrides for a different
# local port or environment:
#
#   LOCAL_URL="http://127.0.0.1:8093" bin/smoke.sh
#
# What it covers:
#   * Read-only route checks against PROD (always) and LOCAL (if a server is
#     listening there) — health, create page, 404 handling, static files.
#   * Feature round-trip against LOCAL ONLY (prod stays read-only / no writes):
#     create an adventure → assert the packing list renders → assert carpool is
#     opt-in (checkbox appears only when enabled) → RSVP "Going" + driving →
#     assert the driver chip shows → delete → assert 404. Fully self-cleaning.
#
# Note: if a LOCAL server is a stale build (left over from another session),
# feature assertions may fail against old code — point LOCAL_URL at a fresh
# server, or kill the stale one first.

LOCAL_URL="${LOCAL_URL:-http://127.0.0.1:8080}"
PROD_URL="${PROD_URL:-https://purbition.com}"

pass=0
fail=0

check() {
  # check <name> <base_url> <path> <expected_code>
  local name="$1" base="$2" path="$3" want="$4"
  local got
  # Retry once with a longer timeout on cold-start: Render's free tier spins
  # down after 15 min idle and a cold boot can take ~60s, blowing past the
  # first 15s timeout. Subsequent requests in the same run are warm + fast.
  got=$(curl -s -o /dev/null -w "%{http_code}" --max-time 15 "$base$path")
  if [ "$got" = "000" ]; then
    sleep 1
    got=$(curl -s -o /dev/null -w "%{http_code}" --max-time 60 "$base$path")
  fi
  if [ "$got" = "$want" ]; then
    printf "  PASS  %-28s %s%s → %s\n" "$name" "$base" "$path" "$got"
    pass=$((pass + 1))
  else
    printf "  FAIL  %-28s %s%s → %s (wanted %s)\n" "$name" "$base" "$path" "$got" "$want"
    fail=$((fail + 1))
  fi
}

grep_page() {
  # grep_page <name> <base_url> <path> <expected_substring>
  # Fetches the page and asserts it CONTAINS the substring (or does not, if
  # the substring is prefixed with "!").
  local name="$1" base="$2" path="$3" expr="$4" body
  body=$(curl -s --max-time 15 "$base$path")
  if [ "${expr:0:1}" = "!" ]; then
    expr="${expr:1}"
    if ! printf '%s' "$body" | grep -qF -- "$expr"; then
      printf "  PASS  %-28s %s%s — lacks '%s'\n" "$name" "$base" "$path" "$expr"
      pass=$((pass + 1))
    else
      printf "  FAIL  %-28s %s%s — unexpectedly contains '%s'\n" "$name" "$base" "$path" "$expr"
      fail=$((fail + 1))
    fi
    return
  fi
  if printf '%s' "$body" | grep -qF -- "$expr"; then
    printf "  PASS  %-28s %s%s — has '%s'\n" "$name" "$base" "$path" "$expr"
    pass=$((pass + 1))
  else
    printf "  FAIL  %-28s %s%s — missing '%s'\n" "$name" "$base" "$path" "$expr"
    fail=$((fail + 1))
  fi
}

# Does a server actually listen at this base? (local servers are optional)
server_up() {
  curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$1/" | grep -q '2\|3\|4\|5'
}

# Feature round-trip against a fresh DB via the real HTTP routes. Creates and
# then deletes one adventure, so nothing survives the run.
feature_roundtrip() {
  local base="$1" sid body
  local marker="smoke-$(date +%s)"

  printf "  --- create adventure (packing_list + carpool ON) ---\n"
  sid=$(curl -s -o /dev/null --max-time 15 -w "%{redirect_url}" \
        -X POST "$base/create" \
        --data-urlencode "name=$marker" \
        --data-urlencode "date=2099-01-01" \
        --data-urlencode "time=09:00" \
        --data-urlencode "location=Smoke Test Spot" \
        --data-urlencode "description=automated feature round-trip" \
        --data-urlencode $'packing_list=Water\nSunscreen' \
        --data-urlencode "carpool=1" \
        | sed 's|.*/||')
  if [ -z "$sid" ] || [ "$sid" = "redirect_url" ]; then
    printf "  FAIL  %-28s create → no share id (route broken?)\n" "create route"
    fail=$((fail + 1))
    return
  fi
  printf "  PASS  %-28s created /adventure/%s\n" "create route" "$sid"
  pass=$((pass + 1))

  grep_page "packing renders"  "$base" "/adventure/$sid" "Packing checklist"
  grep_page "packing item A"   "$base" "/adventure/$sid" ">Water<"
  grep_page "packing item B"   "$base" "/adventure/$sid" ">Sunscreen<"
  # carpool was enabled → the drive checkbox must exist post-RSVP
  grep_page "carpool UI on"    "$base" "/adventure/$sid" "I'm driving"
  # nobody has RSVP'd Going yet → the carpool card (needs going_ppl) is absent
  grep_page "card hidden pre-rsvp" "$base" "/adventure/$sid" "!id=\"carpoolCard\""

  printf "  --- RSVP Smoke Driver Going + driving=1 ---\n"
  body=$(curl -s -o /dev/null -w "%{http_code} %{redirect_url}" --max-time 15 \
        -X POST "$base/adventure/$sid/rsvp" \
        --data-urlencode "name=Smoke Driver" \
        --data-urlencode "status=going" \
        --data-urlencode "driving=1")
  if [ "${body%% *}" = "302" ]; then
    printf "  PASS  %-28s rsvp + driving=1 → 302\n" "rsvp route"
    pass=$((pass + 1))
  else
    printf "  FAIL  %-28s rsvp → %s (wanted 302)\n" "rsvp route" "${body%% *}"
    fail=$((fail + 1))
  fi

  # card renders; driver chip present for the row
  grep_page "card visible post-rsvp" "$base" "/adventure/$sid" "id=\"carpoolCard\""
  grep_page "driver chip"      "$base" "/adventure/$sid" "driver-chip"
  # drivers named (single driver → no separator yet)
  printf "  --- RSVP Bob Going, no driving ---\n"
  curl -s -o /dev/null --max-time 15 -X POST "$base/adventure/$sid/rsvp" \
        --data-urlencode "name=Bob" \
        --data-urlencode "status=going"
  grep_page "driver still named" "$base" "/adventure/$sid" ">Smoke Driver<"
  # Bob joined Going but did not volunteer → he is NOT in the driver list
  grep_page "Bob not a driver"   "$base" "/adventure/$sid" "!Smoke Driver · Bob"
  grep_page "driver list exact"  "$base" "/adventure/$sid" "carpool-driver-head"

  printf "  --- carpool default OFF on a second adventure ---\n"
  local sid2
  sid2=$(curl -s -o /dev/null --max-time 15 -w "%{redirect_url}" \
        -X POST "$base/create" \
        --data-urlencode "name=$marker-2" \
        --data-urlencode "date=2099-01-02" \
        --data-urlencode "location=Smoke Spot B" \
        | sed 's|.*/||')
  # no carpool flag sent → no drive checkbox, no carpool card
  grep_page "carpool default off" "$base" "/adventure/$sid2" "!I'm driving"
  grep_page "no carpool card"     "$base" "/adventure/$sid2" "!No drivers yet"

  printf "  --- cleanup (soft-delete + undo) ---\n"
  for s in "$sid" "$sid2"; do
    local code
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 15 -X POST "$base/adventure/$s/delete")
    if [ "$code" = "302" ]; then
      printf "  PASS  %-28s delete %s → 302\n" "delete route" "$s"
      pass=$((pass + 1))
    else
      printf "  FAIL  %-28s delete %s → %s (wanted 302)\n" "delete route" "$s" "$code"
      fail=$((fail + 1))
    fi
    # Soft-delete: the shared link still loads the deleted-state page (200)
    # instead of 404, and offers an Undo.
    grep_page "deleted state renders" "$base" "/adventure/$s" "deleted"
    check "deleted page 200" "$base" "/adventure/$s" 200
  done
  # Undo the first one and verify it's live again (restores attendee page).
  local undo
  undo=$(curl -s -o /dev/null -w "%{http_code}" --max-time 15 -X POST "$base/adventure/$sid/undo")
  if [ "$undo" = "302" ]; then
    printf "  PASS  %-28s undo %s → 302\n" "undo route" "$sid"
    pass=$((pass + 1))
  else
    printf "  FAIL  %-28s undo %s → %s (wanted 302)\n" "undo route" "$sid" "$undo"
    fail=$((fail + 1))
  fi
  # Hard-remove the temp adventures (one restored, one soft-deleted) so the
  # local DB stays exactly as it was — even though soft-delete normally keeps
  # rows around for the undo window.
  if [ -f "$(dirname "$0")/../.venv/bin/python" ]; then
    (command cd "$(dirname "$0")/.." && \
      FLASK_ENV=development .venv/bin/python -c "
from models import get_db
for sid in ['$sid', '$sid2']:
    with get_db() as c:
        r = c.execute('SELECT id FROM adventures WHERE share_id = ?', (sid,)).fetchone()
        if r:
            c.execute('DELETE FROM attendees WHERE adventure_id = ?', (r['id'],))
            c.execute('DELETE FROM adventures WHERE id = ?', (r['id'],))
        c.commit()
" 2>/dev/null) || true
  fi
}

echo "== PROD ($PROD_URL) — read-only =="
check "home"            "$PROD_URL" "/"                      200
check "create page"     "$PROD_URL" "/create"                200
check "missing adv 404" "$PROD_URL" "/adventure/does-not-exist" 404
check "static css"      "$PROD_URL" "/static/style.css"      200
check "health"          "$PROD_URL" "/health"                200

if server_up "$LOCAL_URL"; then
  echo ""
  echo "== LOCAL ($LOCAL_URL) — read-only =="
  check "home"            "$LOCAL_URL" "/"                    200
  check "create page"     "$LOCAL_URL" "/create"              200
  check "missing adv 404" "$LOCAL_URL" "/adventure/does-not-exist" 404
  check "static css"      "$LOCAL_URL" "/static/style.css"    200
  check "health"          "$LOCAL_URL" "/health"              200
  echo ""
  echo "== LOCAL ($LOCAL_URL) — feature round-trip =="
  feature_roundtrip "$LOCAL_URL"
else
  echo ""
  echo "== LOCAL ($LOCAL_URL) skipped — no server listening =="
fi

echo ""
printf "Result: %d passed, %d failed\n" "$pass" "$fail"
[ "$fail" -eq 0 ]