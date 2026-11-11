// Adventure — static/app.js
// Progressive enhancement: AJAX RSVP, toast notifications, copy/share link

(function() {
  'use strict';

  // Decode HTML entities (e.g. &quot; -> "). The weather day buttons store an
  // escaped SVG string in data-day-icon; without this, clicking a day injects
  // literal &quot; text and the icon breaks.
  function decodeEntities(s) {
    const t = document.createElement('textarea');
    t.innerHTML = s;
    return t.value;
  }

  // ==========================================================================
  // Toast Notifications
  // ==========================================================================
  function showToast(message, type = 'success') {
    const toast = document.getElementById('toast');
    if (!toast) return;

    toast.textContent = message;
    toast.className = 'toast show toast-' + type;

    if (toast._timeout) {
      clearTimeout(toast._timeout);
    }

    toast._timeout = setTimeout(() => {
      toast.classList.remove('show');
    }, 2500);
  }

  window.showToast = showToast;

  // ==========================================================================
  // Inline error display (shows errors near form fields instead of toasts)
  // ==========================================================================
  function showInlineError(form, fieldName, message) {
    // Remove any existing error for this field
    clearInlineError(form, fieldName);

    const input = form.querySelector(`[name="${fieldName}"]`);
    if (!input) return;

    const error = document.createElement('span');
    error.className = 'inline-error';
    error.textContent = message;
    input.parentNode.appendChild(error);
    input.classList.add('input-error');
  }

  function clearInlineError(form, fieldName) {
    const input = form.querySelector(`[name="${fieldName}"]`);
    if (!input) return;
    const error = input.parentNode.querySelector('.inline-error');
    if (error) error.remove();
    input.classList.remove('input-error');
  }

  // Clear inline errors when user starts typing
  document.addEventListener('input', (e) => {
    const input = e.target;
    if (input.matches('input, select, textarea')) {
      const error = input.parentNode.querySelector('.inline-error');
      if (error) {
        error.remove();
        input.classList.remove('input-error');
      }
    }
  });

  // ==========================================================================
  // Category picker on the flat edit form (single-select option buttons).
  function initCategoryPicker() {
    const input = document.getElementById('categoryPickerInput');
    if (!input) return;
    const opts = Array.from(document.querySelectorAll('.category-opt'));
    opts.forEach(opt => {
      opt.addEventListener('click', () => {
        const id = opt.dataset.vibe;
        const wasSelected = opt.classList.contains('selected');
        // Clear all, then re-select the clicked one (toggle off if re-clicked).
        opts.forEach(o => { o.classList.remove('selected'); o.setAttribute('aria-pressed', 'false'); });
        if (!wasSelected) {
          opt.classList.add('selected');
          opt.setAttribute('aria-pressed', 'true');
          input.value = id;
        } else {
          input.value = '';
        }
      });
    });
  }

  // Share: Native Web Share API + clipboard fallback
  // ==========================================================================
  function initShareButton() {
    const shareBtn = document.getElementById('shareBtn');
    if (!shareBtn) return;

    const url = shareBtn.dataset.url || window.location.href;
    const title = document.querySelector('.adventure-cover h1')?.textContent || 'Purbition';
    const text = decodeURIComponent(shareBtn.dataset.message) || `Check out this adventure: ${title}`;

    // Try native share first (mobile)
    if (navigator.share) {
      shareBtn.addEventListener('click', async () => {
        try {
          await navigator.share({ title, text, url });
        } catch (err) {
          if (err.name !== 'AbortError') {
            fallbackCopy(url);
          }
        }
      });
      return;
    }

    // Fallback: copy to clipboard
    shareBtn.addEventListener('click', () => fallbackCopy(url));
  }

  async function fallbackCopy(url) {
    const shareBtn = document.getElementById('shareBtn');
    try {
      await navigator.clipboard.writeText(url);
      showToast('Link copied!');
      if (shareBtn) {
        const original = shareBtn.textContent;
        shareBtn.textContent = 'Copied!';
        shareBtn.classList.add('btn-success');
        setTimeout(() => {
          shareBtn.textContent = original;
          shareBtn.classList.remove('btn-success');
        }, 2000);
      }
    } catch (err) {
      showToast('Could not copy link', 'error');
    }
  }

  // ==========================================================================
  // AJAX RSVP - updates DOM without reload
  // ==========================================================================
  function statusLabel(status) {
    return { going: 'Going', interested: 'Interested', cant: "Can't go" }[status] || '';
  }

  function initRsvpForms() {
    const forms = document.querySelectorAll('.rsvp-form');
    if (!forms.length) return;

    forms.forEach(form => {
      // Track selected status — pills toggle state, primary button submits.
      let selectedStatus = 'going';

      form.querySelectorAll('.status-btn').forEach(btn => {
        btn.addEventListener('click', () => {
          // Toggle active state
          form.querySelectorAll('.status-btn').forEach(b => {
            b.classList.remove('active');
            b.setAttribute('aria-pressed', 'false');
          });
          btn.classList.add('active');
          btn.setAttribute('aria-pressed', 'true');
          selectedStatus = btn.value;

          // Show/hide the +1 section when Going is selected.
          const plusOne = form.querySelector('#plusOneGroup');
          if (plusOne) plusOne.hidden = selectedStatus !== 'going';
        });
      });

      // Toggle the name field when the +1 checkbox is clicked.
      const plusOneToggle = form.querySelector('#plusOneToggle');
      const plusOneNameField = form.querySelector('.plus-one-name-field');
      const plusOneNameInput = form.querySelector('input[name="plus_one_name"]');
      if (plusOneToggle && plusOneNameField && plusOneNameInput) {
        plusOneToggle.addEventListener('change', () => {
          if (plusOneToggle.checked) {
            plusOneNameField.hidden = false;
            plusOneNameInput.focus();
          } else {
            plusOneNameField.hidden = true;
            plusOneNameInput.value = '';
          }
        });
        // Auto-submit when the +1 name is finished (blur or Enter)
        plusOneNameInput.addEventListener('blur', () => {
          if (plusOneToggle.checked && plusOneNameInput.value.trim()) {
            form.requestSubmit();
          }
        });
        plusOneNameInput.addEventListener('keydown', (e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            if (plusOneToggle.checked && plusOneNameInput.value.trim()) {
              form.requestSubmit();
            }
          }
        });
      }

      form.addEventListener('submit', async function(e) {
        // First-time RSVP: a name is required.
        const nameInput = this.querySelector('input[name="name"]');
        if (nameInput && !nameInput.value.trim()) {
          e.preventDefault();
          nameInput.focus();
          showInlineError(this, 'name', 'Please enter your name');
          return;
        }

        // If Going with +1 checked, require the +1 name.
        if (selectedStatus === 'going') {
          const plusOneToggle = form.querySelector('#plusOneToggle');
          const plusOneNameInput = form.querySelector('input[name="plus_one_name"]');
          if (plusOneToggle && plusOneToggle.checked && !plusOneNameInput.value.trim()) {
            e.preventDefault();
            plusOneNameInput.focus();
            showInlineError(this, 'plus_one_name', 'Please enter your +1 name');
            return;
          }
        }

        e.preventDefault(); // we handle the submit via fetch

        // Build the payload
        const formData = new FormData(this);
        formData.append('status', selectedStatus);

        // Loading state on the primary submit button
        const submitBtn = this.querySelector('button[type="submit"]');
        const originalText = submitBtn ? submitBtn.textContent : '';
        if (submitBtn) {
          submitBtn.disabled = true;
          submitBtn.dataset.loading = 'true';
          submitBtn.dataset.originalText = originalText;
          submitBtn.innerHTML = '<span class="spinner"></span>';
        }

        try {
          const response = await fetch(this.action, {
            method: 'POST',
            body: formData,
            headers: {
              'X-Requested-With': 'XMLHttpRequest'
            }
          });

            if (response.ok) {
            const data = await response.json();
            handleRsvpSuccess(data);
            if (data.my_status === 'going' && submitBtn) celebrate(submitBtn);
            if (data.carpool_html) insertCarpoolFragment(data.carpool_html);
          } else if (response.redirected) {
            // Fallback: full redirect
            window.location.href = response.url;
          } else {
            // Surface the server's specific message when it returns one
            let msg = 'Something went wrong. Please try again.';
            try {
              const data = await response.json();
              if (data && data.error) msg = data.error;
            } catch (_) { /* non-JSON error body — keep the fallback */ }
            // Show inline error on the relevant field, fall back to toast
            if (data && data.error) {
              const lowerMsg = data.error.toLowerCase();
              if (lowerMsg.includes('name')) {
                showInlineError(this, 'name', data.error);
              } else if (lowerMsg.includes('plus')) {
                showInlineError(this, 'plus_one_name', data.error);
              } else {
                showToast(msg, 'error');
              }
            } else {
              showToast(msg, 'error');
            }
          }
        } catch (err) {
          console.error('RSVP error:', err);
          showToast('Something went wrong. Please try again.', 'error');
        } finally {
          if (submitBtn) {
            submitBtn.disabled = false;
            delete submitBtn.dataset.loading;
            submitBtn.textContent = submitBtn.dataset.originalText || originalText;
          }
        }
      });
    });

  }

  function handleRsvpSuccess(data) {
    // User re-clicked their active status = they removed themselves. The server
    // already hard-deleted their row and cleared their cookie; reload so the
    // page re-renders a fresh RSVP card (blank name input, no "you're on the
    // list" note, updated attendee list/count).
    if (data.removed) {
      // Forget the auto-filled name for this adventure so a stale name doesn't
      // pre-fill when they re-RSVP under a (possibly different) name.
      const shareId = window.location.pathname.split('/')[2];
      if (shareId) localStorage.removeItem('rsvp_name_' + shareId);
      showToast("You've been removed.", 'success');
      window.location.reload();
      return;
    }

    // Update going count
    const countEl = document.querySelector('.going-count .count');
    const labelEl = document.querySelector('.going-count .label');
    if (countEl && data.going_count !== undefined) {
      countEl.textContent = data.going_count;
    }
    if (labelEl && data.going_count !== undefined) {
      labelEl.textContent = data.going_count === 1 ? 'person going' : 'people going';
    }

    // Keep the who's-going avatar stack in sync (faces over counts). If nobody
    // is going anymore, the server-rendered stack is removed too.
    const headEl = document.querySelector('.adventure-card .card-head');
    if (headEl && data.attendees) {
      const hasGoing = data.attendees.some(a => a.status === 'going');
      if (hasGoing) renderAvatarStack(headEl, data.attendees);
      else {
        const stack = headEl.querySelector('.avatar-stack');
        if (stack) stack.remove();
      }
    }

    // Names that were already on the list before this RSVP
    const existingNames = new Set(
      Array.from(document.querySelectorAll('.attendee-name'))
        .map(el => el.textContent.trim())
    );

    // Update attendee list
    const listEl = document.querySelector('.attendee-list');
    const emptyEl = document.querySelector('.empty-attendees');

    if (data.attendees && data.attendees.length > 0) {
      if (emptyEl) emptyEl.remove();
      if (!listEl) {
        // Create list if it didn't exist (inside the attendee card, before actions)
        const card = document.querySelector('.adventure-card');
        const newList = document.createElement('ul');
        newList.className = 'attendee-list';
        renderAttendees(data.attendees, newList, existingNames);
        card.appendChild(newList);
      } else {
        renderAttendees(data.attendees, listEl, existingNames);
      }
    } else if (listEl) {
      listEl.remove();
      // Show empty state
      const card = document.querySelector('.adventure-card');
      const newEmpty = document.createElement('p');
      newEmpty.className = 'empty-attendees';
      newEmpty.textContent = 'No RSVPs yet. Be the first!';
      card.appendChild(newEmpty);
    }

    // First-time RSVP: swap the name form for the "you're on the list" note.
    const nameGroup = document.getElementById('rsvpNameGroup');
    if (nameGroup && data.my_status) {
      const name = nameGroup.querySelector('input[name="name"]').value.trim();
      nameGroup.remove();
      const label = document.getElementById('rsvpLabel');
      if (label) label.textContent = 'Your RSVP';
      const note = document.createElement('p');
      note.className = 'my-rsvp-note';
      note.innerHTML = "You're on the list as <strong>" + escapeHtml(name) + "</strong> " +
        '<span class="my-rsvp-says">(' + statusLabel(data.my_status) + ')</span>';
      const group = document.querySelector('.status-group');
      if (group) group.insertAdjacentElement('beforebegin', note);
    }

    // Move the highlighted pill to match the (possibly new) status.
    if (data.my_status) {
      document.querySelectorAll('.status-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.status === data.my_status);
        btn.setAttribute('aria-pressed', btn.dataset.status === data.my_status ? 'true' : 'false');
      });
      const saysEl = document.querySelector('.my-rsvp-says');
      if (saysEl) saysEl.textContent = '(' + statusLabel(data.my_status) + ')';
      syncDriveGroup(data.my_status);

      // Plus-one field only shows when Going.
      const plusOne = document.getElementById('plusOneGroup');
      if (plusOne) plusOne.hidden = data.my_status !== 'going';
    }

    showToast('RSVP saved!');
  }

  // Show the "I can drive" checkbox only while your status is Going.
  // (Leaving the form also clears it — an unchecked box sends nothing = 0.)
  function syncDriveGroup(status) {
    const group = document.getElementById('driveGroup');
    if (group) group.hidden = status !== 'going';
  }

  // Insert the carpool card fragment returned by the server (single source
  // of truth). The server renders the card after every action; this just swaps
  // the node in and hides it when there's nothing to show.
  function insertCarpoolFragment(html) {
    const card = document.getElementById('carpoolCard');
    if (!card) return;
    const tmp = document.createElement('div');
    tmp.innerHTML = html.trim();
    const fresh = tmp.querySelector('#carpoolCard');
    if (fresh) {
      card.replaceWith(fresh);
    } else {
      // Server sent an empty body -> card has no content, hide it.
      card.hidden = true;
    }
  }

  // ─── Creator carpool controls ───────────────────────────────────────────────
  // Wire up the pencil-buttons, inline-edit forms, and move-rider dropdowns.
  // Called once at init time; handles both server-rendered and AJAX content.
  function initCarpoolActions() {
    // Peer-to-peer carpool URL. Read from the form's data-url (NOT form.action,
    // which is shadowed by the hidden <input name="action"> inside carpool forms).
    const existingForm = document.querySelector('.carpool-action-form');
    window._carpoolActionUrl = existingForm ? (existingForm.dataset.url || existingForm.getAttribute('action') || null) : null;

    // Creator endpoint URL (stamped on the card by the server as data-creator-url)
    const carpoolCard = document.getElementById('carpoolCard');
    window._carpoolCreatorUrl = carpoolCard
      ? carpoolCard.dataset.creatorUrl || null
      : null;

    // Shared helper: AJAX submit any carpool form and re-render on success.
    async function submitCarpoolForm(form, postUrl) {
      const submitBtn = form.querySelector('button[type="submit"]');
      const originalHTML = submitBtn ? submitBtn.innerHTML : '';
      if (submitBtn) { submitBtn.disabled = true; submitBtn.innerHTML = '\u2026'; }

      try {
        const fd = new FormData(form);
        const resp = await fetch(postUrl, {
          method: 'POST',
          body: fd,
          headers: { 'X-Requested-With': 'XMLHttpRequest' },
        });
        if (resp.redirected) { window.location.href = resp.url; return; }
        const data = await resp.json();
        if (data.ok) {
          showToast(data.flash || 'Done!', 'success');
          insertCarpoolFragment(data.html);
        } else {
          showToast(data.flash || 'Something went wrong', 'error');
        }
      } catch (err) {
        console.error('Carpool action error:', err);
        showToast('Could not save. Please try again.', 'error');
      } finally {
        if (submitBtn) { submitBtn.disabled = false; submitBtn.innerHTML = originalHTML; }
      }
    }

    // ── Pencil button → show inline edit form ──────────────────────────────────
    document.addEventListener('click', function(e) {
      const pencil = e.target.closest('.carpool-edit-driver');
      if (!pencil) return;
      const driverDiv = pencil.closest('.carpool-driver');
      if (!driverDiv) return;
      const editForm = driverDiv.querySelector('.carpool-edit-form');
      if (editForm) editForm.hidden = false;
      pencil.style.display = 'none';
    });

    // ── Cancel button → hide inline edit form ──────────────────────────────────
    document.addEventListener('click', function(e) {
      const cancel = e.target.closest('.carpool-edit-cancel');
      if (!cancel) return;
      const editForm = cancel.closest('.carpool-edit-form');
      if (!editForm) return;
      editForm.hidden = true;
      // Restore pencil button
      const driverDiv = editForm.closest('.carpool-driver');
      if (driverDiv) {
        const pencil = driverDiv.querySelector('.carpool-edit-driver');
        if (pencil) pencil.style.display = '';
      }
    });

    // ── Edit-driver form → AJAX submit ─────────────────────────────────────────
    document.addEventListener('submit', function(e) {
      const editForm = e.target.closest('.carpool-edit-form');
      if (!editForm) return;
      e.preventDefault();
      const creatorUrl = window._carpoolCreatorUrl ||
        (editForm.dataset.url || window._carpoolActionUrl || '');
      submitCarpoolForm(editForm, creatorUrl);
    });

    // ── All carpool-action-forms (claim_rider / claim_driver / unclaim /
    //     move_rider) → AJAX submit ─────────────────────────────────────────────
    document.addEventListener('submit', async function(e) {
      const form = e.target.closest('.carpool-action-form');
      if (!form) return;

      e.preventDefault();
      const actionField = form.querySelector('[name="action"]');
      if (!actionField) return;

      // move_rider uses rider_id + driver_id; others use attendee_id
      const hasAttendeeId = !!form.querySelector('[name="attendee_id"]');
      const hasRiderId    = !!form.querySelector('[name="rider_id"]');
      if (!hasAttendeeId && !hasRiderId) return;

      const postUrl = form.dataset.url || window._carpoolActionUrl || '';
      await submitCarpoolForm(form, postUrl);
    });

  }

  // ─── Cost breakdown card ──────────────────────────────────────────────────
  // The cost card is a server-rendered partial (_cost_card.html). Every add /
  // delete posts to the server via fetch; on success we splice in the freshly
  // rendered fragment so the card can't drift from the template. Mirrors the
  // carpool card pattern.
  function initCostCard() {
    const card = document.getElementById('costCard');
    if (!card) return;

    function insertCostFragment(html) {
      const tmp = document.createElement('template');
      tmp.innerHTML = html.trim();
      const fresh = tmp.content.querySelector('#costCard');
      if (!fresh) return;
      card.replaceWith(fresh);
      initCostCard(); // re-bind after the card is swapped
    }

    document.addEventListener('submit', async (e) => {
      const form = e.target.closest('.cost-add-form, .cost-delete-form');
      if (!form || !form.closest('#costCard')) return;
      if (form.classList.contains('cost-delete-form') && !confirm('Remove this cost line?')) {
        e.preventDefault(); return;
      }
      e.preventDefault();
      const btn = form.querySelector('button[type="submit"]');
      const orig = btn ? btn.innerHTML : '';
      if (btn) { btn.disabled = true; }
      try {
        const fd = new FormData(form);
        const resp = await fetch(form.action, {
          method: 'POST',
          body: fd,
          headers: { 'X-Requested-With': 'XMLHttpRequest' },
        });
        if (resp.redirected) { window.location.href = resp.url; return; }
        const data = await resp.json();
        if (data.ok) {
          showToast(data.flash || 'Done', 'success');
          if (data.html) insertCostFragment(data.html);
        } else {
          showToast(data.flash || 'Could not save, please try again.', 'error');
        }
      } catch (err) {
        console.error('Cost action error:', err);
        showToast('Could not save. Please try again.', 'error');
      } finally {
        if (btn) { btn.disabled = false; }
      }
    });
  }

  function initSplitsCard() {
    const card = document.getElementById('splitsCard');
    if (!card) return;

    function insertSplitsFragment(html) {
      const tmp = document.createElement('template');
      tmp.innerHTML = html.trim();
      const fresh = tmp.content.querySelector('#splitsCard');
      if (!fresh) return;
      card.replaceWith(fresh);
      initSplitsCard(); // re-bind after the card is swapped
    }

    document.addEventListener('submit', async (e) => {
      const form = e.target.closest(
        '.expense-add-form, .expense-delete-form, .venmo-form, .splits-toggle-form'
      );
      if (!form || !form.closest('#splitsCard')) return;
      if (form.classList.contains('expense-delete-form') && !confirm('Remove this expense and its split math?')) {
        e.preventDefault(); return;
      }
      e.preventDefault();
      const btn = form.querySelector('button[type="submit"]');
      const orig = btn ? btn.innerHTML : '';
      if (btn) { btn.disabled = true; }
      try {
        const fd = new FormData(form);
        const resp = await fetch(form.action, {
          method: 'POST',
          body: fd,
          headers: { 'X-Requested-With': 'XMLHttpRequest' },
        });
        if (resp.redirected) { window.location.href = resp.url; return; }
        const data = await resp.json();
        if (data.ok) {
          showToast(data.flash || 'Done', 'success');
          if (data.html) insertSplitsFragment(data.html);
        } else {
          showToast(data.flash || 'Could not save, please try again.', 'error');
        }
      } catch (err) {
        console.error('Splits action error:', err);
        showToast('Could not save. Please try again.', 'error');
      } finally {
        if (btn) { btn.disabled = false; }
      }
    });
  }

  function initPackingCard() {
    const card = document.getElementById('packingCard');
    if (!card) return;

    function insertPackingFragment(html) {
      const tmp = document.createElement('template');
      tmp.innerHTML = html.trim();
      const fresh = tmp.content.querySelector('#packingCard');
      if (!fresh) return;
      card.replaceWith(fresh);
      initPackingCard(); // re-bind after the card is swapped
    }

    document.addEventListener('submit', async (e) => {
      const form = e.target.closest(
        '.packing-add-form, .packing-delete-form, .packing-claim-form, .packing-unclaim-form'
      );
      if (!form || !form.closest('#packingCard')) return;
      if (form.classList.contains('packing-delete-form') && !confirm('Remove this gear item?')) {
        e.preventDefault(); return;
      }
      e.preventDefault();
      const btn = form.querySelector('button[type="submit"]');
      if (btn) { btn.disabled = true; }
      try {
        const fd = new FormData(form);
        const resp = await fetch(form.action, {
          method: 'POST',
          body: fd,
          headers: { 'X-Requested-With': 'XMLHttpRequest' },
        });
        if (resp.redirected) { window.location.href = resp.url; return; }
        const data = await resp.json();
        if (data.ok) {
          showToast(data.flash || 'Done', 'success');
          if (data.html) insertPackingFragment(data.html);
          // after add, put focus back in the (now-empty) add input
          const freshAdd = document.querySelector('.packing-add-form input[name="label"]');
          if (freshAdd && e.target.matches('.packing-add-form')) freshAdd.focus();
        } else {
          showToast(data.flash || 'Could not save, please try again.', 'error');
        }
      } catch (err) {
        console.error('Packing action error:', err);
        showToast('Could not save. Please try again.', 'error');
      } finally {
        if (btn) { btn.disabled = false; }
      }
    });
  }

  function celebrate(anchor) {
    // Tiny sparkle burst anchored to the tapped RSVP button. Skipped when the
    // user prefers reduced motion.
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const rect = anchor.getBoundingClientRect();
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;
    const colors = ['var(--going)', 'var(--denim-light)', 'var(--denim-lighter)', 'var(--interested)'];
    const COUNT = 18;
    const host = document.createElement('div');
    host.className = 'confetti';
    host.style.left = cx + 'px';
    host.style.top = cy + 'px';
    for (let i = 0; i < COUNT; i++) {
      const p = document.createElement('i');
      const angle = (Math.PI * 2 * i) / COUNT + Math.random() * 0.7;
      const dist = 90 + Math.random() * 90;
      p.style.setProperty('--dx', (Math.cos(angle) * dist).toFixed(1) + 'px');
      p.style.setProperty('--dy', (Math.sin(angle) * dist - 24).toFixed(1) + 'px');
      p.style.setProperty('--rot', (Math.random() * 360).toFixed(0) + 'deg');
      p.style.setProperty('--delay', (Math.random() * 0.06).toFixed(3) + 's');
      p.style.setProperty('--c', colors[i % colors.length]);
      host.appendChild(p);
    }
    document.body.appendChild(host);
    setTimeout(() => host.remove(), 1200);
  }

  window.celebrate = celebrate;

  function renderAttendees(attendees, container, existingNames = new Set()) {
    container.innerHTML = '';
    attendees.forEach(a => {
      const isNew = !existingNames.has(a.name);
      const li = document.createElement('li');
      li.className = `attendee attendee-${a.status}` + (isNew ? ' attendee-in' : '');
      const driverChip = a.status === 'going' && a.driving
        ? '<span class="driver-chip">driver</span>' : '';
      const plusOne = a.status === 'going' && a.plus_one_name
        ? '<span class="plus-one-badge">+1 ' + escapeHtml(a.plus_one_name) + '</span>'
        : '';
      li.innerHTML = `
        <span class="attendee-name">${escapeHtml(a.name)}</span>
        <span class="attendee-trailing">
          ${driverChip}
          ${plusOne}
          <span class="attendee-status status-${a.status}">
            ${a.status === 'going' ? 'Going' : a.status === 'interested' ? 'Interested' : "Can't go"}
          </span>
        </span>
      `;
      container.appendChild(li);
    });
  }

  // ==========================================================================
  // Weather strip — click a day to swap the hero card to that day's forecast
  // ==========================================================================
  // ==========================================================================
// Collapsible sections (cost breakdown default closed; user choice persists
// per-adventure in localStorage)
// ==========================================================================
function initCollapsibles() {
  const heads = document.querySelectorAll('[data-collapsible-toggle]');
  if (!heads.length) return;
  const shareId = (window.location.pathname.split('/')[2]) || 'global';

  heads.forEach((btn) => {
    const key = btn.dataset.collapsibleToggle;
    const section = btn.closest('[data-collapsible]');
    const body = document.getElementById(btn.getAttribute('aria-controls'));
    if (!section || !body) return;

    // Restore the user's previous state (default: closed)
    const stored = localStorage.getItem('collapsible_' + key + '_' + shareId);
    const open = stored === '1';
    setOpen(section, body, btn, open);

    btn.addEventListener('click', () => {
      const nowOpen = section.getAttribute('aria-expanded') !== 'true';
      setOpen(section, body, btn, nowOpen);
      localStorage.setItem('collapsible_' + key + '_' + shareId, nowOpen ? '1' : '0');
    });
  });

  function setOpen(section, body, btn, isOpen) {
    section.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
    btn.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
    if (isOpen) body.removeAttribute('hidden'); else body.setAttribute('hidden', '');
  }
}

function initWeatherStrip() {
    const strip = document.getElementById('weatherStrip');
    const hero = document.getElementById('weatherHero');
    if (!strip || !hero) return;
    const iconEl = document.getElementById('weatherHeroIcon');
    const dayEl = document.getElementById('weatherHeroDay');
    const condEl = document.getElementById('weatherHeroCondition');
    const highEl = document.getElementById('weatherHeroHigh');
    const lowEl = document.getElementById('weatherHeroLow');
    if (!iconEl || !dayEl || !condEl || !highEl || !lowEl) return;

    function selectDay(day) {
      iconEl.innerHTML = decodeEntities(day.dataset.dayIcon);
      dayEl.textContent = day.dataset.dayLabel;
      condEl.textContent = day.dataset.dayCondition;
      highEl.textContent = day.dataset.dayHigh + '\u00b0';
      lowEl.textContent = day.dataset.dayLow + '\u00b0';
      strip.querySelectorAll('.weather-day').forEach(d => {
        d.classList.remove('weather-day-active');
        d.setAttribute('aria-selected', 'false');
      });
      day.classList.add('weather-day-active');
      day.setAttribute('aria-selected', 'true');
    }

    strip.querySelectorAll('.weather-day').forEach(day => {
      day.addEventListener('click', () => selectDay(day));
      day.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); selectDay(day); }
      });
    });
  }

  // ==========================================================================
  // Create form loading state
  // ==========================================================================
  function initCreateForm() {
    const form = document.querySelector('.adventure-form');
    if (!form) return;

    form.addEventListener('submit', function(e) {
      const btn = this.querySelector('button[type="submit"]');
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner"></span> Creating...';
      }
    });
  }

  // ==========================================================================
  // Create wizard (reference-inspired: vibe > details > review)
  // ==========================================================================
  const MONTHS = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN',
                  'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];

  function initWizard() {
    const form = document.getElementById('wizardForm');
    if (!form) return;

    const head = document.getElementById('wizardHead');
    const labelEl = document.getElementById('wizardStepLabel');
    const progressEl = document.getElementById('wizardProgress');
    const steps = Array.from(form.querySelectorAll('.wizard-step'));
    const vibeInput = document.getElementById('vibeInput');
    const vibeCards = Array.from(document.querySelectorAll('.vibe-card'));
    const stepLabels = [
      null,
      '01 \u00b7 pick a category',
      '02 \u00b7 add the details',
      '03 \u00b7 review & create',
    ];

    let current = parseInt((head && head.dataset.startStep) || '1', 10) || 1;

    function show(step) {
      current = step;
      steps.forEach(s => {
        const on = parseInt(s.dataset.step, 10) === step;
        s.hidden = !on;
        if (on && step === 3) refreshReview();
      });
      if (labelEl) labelEl.textContent = stepLabels[step] || '';
      if (progressEl) progressEl.style.width = [33, 66, 100][step - 1] + '%';
      // Scroll to top of the wizard area so the new step is in view.
      const top = (head || form).getBoundingClientRect().top + window.scrollY - 64;
      window.scrollTo({ top, behavior: 'smooth' });
    }

    // --- vibe picker (single select) ---
    function selectVibe(id) {
      vibeCards.forEach(card => {
        const isSel = card.dataset.vibe === id;
        card.classList.toggle('selected', isSel);
        card.setAttribute('aria-pressed', isSel ? 'true' : 'false');
      });
      if (vibeInput) vibeInput.value = id || '';
    }

    vibeCards.forEach(card => {
      card.addEventListener('click', () => {
        selectVibe(card.dataset.vibe);
      });
    });

    // If the server re-rendered with errors, respect the preselected vibe.
    if (vibeInput && vibeInput.value) selectVibe(vibeInput.value);

    // --- validation on the details step ---
    function detailsAreValid() {
      const req = ['name', 'date', 'location'];
      for (const id of req) {
        const el = document.getElementById(id);
        if (el && !el.value.trim()) {
          el.focus();
          showToast('Please fill in the ' + id + ' field', 'error');
          return false;
        }
      }
      return true;
    }

    // --- review card population ---
    function refreshReview() {
      const val = id => {
        const el = document.getElementById(id);
        return el ? el.value.trim() : '';
      };
      const name = val('name');
      const dateStr = val('date');
      const timeStr = val('time');
      const loc = val('location');
      const desc = val('description');
      const vibeId = vibeInput ? vibeInput.value : '';
      const picked = vibeCards.find(c => c.dataset.vibe === vibeId);

      const reviewName = document.getElementById('reviewName');
      const reviewVibe = document.getElementById('reviewVibe');
      const reviewMonth = document.getElementById('reviewMonth');
      const reviewDay = document.getElementById('reviewDay');
      const reviewWhen = document.getElementById('reviewWhen');
      const reviewLoc = document.getElementById('reviewLoc');
      const reviewDesc = document.getElementById('reviewDesc');

      if (reviewName) reviewName.textContent = name || 'Unnamed adventure';
      if (reviewVibe) {
        reviewVibe.textContent = (picked ? picked.querySelector('.vibe-title').textContent : '').toUpperCase() || 'NO CATEGORY';
      }

      if (dateStr) {
        const [y, m, d] = dateStr.split('-').map(Number);
        const dt = new Date(y, m - 1, d);
        const weekday = dt.toLocaleDateString('en-US', { weekday: 'long' });
        const month = MONTHS[m - 1];
        if (reviewMonth) reviewMonth.textContent = month;
        if (reviewDay) reviewDay.textContent = String(d);

        const endDateStr = val('end_date');
        const endTimeStr = val('end_time');
        if (endDateStr) {
          const [ey, em, ed] = endDateStr.split('-').map(Number);
          const edt = new Date(ey, em - 1, ed);
          const eweekday = edt.toLocaleDateString('en-US', { weekday: 'long' });
          const emonth = MONTHS[em - 1];
          if (reviewWhen) {
            reviewWhen.textContent = `${weekday}, ${month} ${d} \u2013 ${eweekday}, ${emonth} ${ed} \u00b7 ${prettyTime(timeStr)}${endTimeStr ? ' \u2013 ' + prettyTime(endTimeStr) : ''}`;
          }
        } else {
          if (reviewWhen) {
            reviewWhen.textContent = `${weekday}, ${month} ${d} \u00b7 ${prettyTime(timeStr)}`;
          }
        }
      }
      if (reviewLoc) reviewLoc.textContent = loc || 'Somewhere great';
      if (reviewDesc) {
        reviewDesc.hidden = !desc;
        reviewDesc.textContent = desc;
      }

      // Series-count warning: when a recurrence is picked, this creates a
      // whole series, not one link. Tell the host what they're about to make.
      const reviewSeries = document.getElementById('reviewSeriesWarning');
      if (reviewSeries) {
        const rule = val('recurrence_rule');
        if (rule) {
          const countEl = document.getElementById('occurrence_count');
          let count = countEl ? parseInt(countEl.value, 10) : 0;
          if (!count || count < 1) count = 6; // server default when a cadence is picked
          const total = 1 + count;
          reviewSeries.textContent =
            `This is a series \u2014 it will create ${total} events (this one + ${count} more), each with its own link and RSVP list.`;
          reviewSeries.hidden = false;
        } else {
          reviewSeries.hidden = true;
        }
      }
    }

    // --- nav buttons ---
    form.querySelectorAll('.wizard-next').forEach(btn => {
      btn.addEventListener('click', () => {
        const next = parseInt(btn.dataset.goto, 10);
        if (current === 2 && next === 3 && !detailsAreValid()) return;
        show(next);
      });
    });
    form.querySelectorAll('.wizard-back').forEach(btn => {
      btn.addEventListener('click', () => show(parseInt(btn.dataset.goto, 10)));
    });

    // Enter in a single-line input advances to review instead of POSTing early.
    form.addEventListener('keydown', e => {
      if (e.key === 'Enter' && e.target.matches('input')) {
        e.preventDefault();
        if (current === 2 && detailsAreValid()) show(3);
      }
    });

    show(current);
  }

  function prettyTime(timeStr) {
    if (!timeStr) return 'All day';
    const [h, mi] = timeStr.split(':');
    const hr = parseInt(h, 10);
    const ap = hr >= 12 ? 'PM' : 'AM';
    return `${hr % 12 || 12}:${mi} ${ap}`;
  }

  // ==========================================================================
  // Delete confirmation
  // ==========================================================================
  function initDeleteForm() {
    const form = document.getElementById('deleteForm');
    if (!form) return;
    form.addEventListener('submit', function(e) {
      if (!confirm('Delete this adventure? This removes the page and all RSVPs. This cannot be undone.')) {
        e.preventDefault();
      }
    });
  }

  // ==========================================================================
  // Series-cancel confirmation (delete all FUTURE occurrences at once)
  // ==========================================================================
  function initSeriesCancel() {
    document.addEventListener('submit', function(e) {
      const form = e.target.closest('.series-cancel-form');
      if (!form) return;
      const count = (form.parentElement && form.parentElement.parentElement
        ? form.parentElement.parentElement.querySelectorAll('.series-item').length
        : 0) + 1;
      if (!confirm('Cancel all future occurrences of this series? That\'s this one plus ' + count + ' more. Each page gets a 24h undo, but it\'s a lot of links to undo.')) {
        e.preventDefault();
      }
    });
  }

  // ==========================================================================
  // Manage page (/manage) — confirm before deleting a whole adventure row
  // ==========================================================================
  function initManageDeleteForm() {
    document.addEventListener('submit', function(e) {
      const form = e.target;
      if (!form || !form.hasAttribute('data-confirm-delete')) return;
      const name = form.dataset.confirmDelete || 'this event';
      if (!confirm('Delete "' + name + '"? It moves to the deleted state (undoable from its page for 24h).')) {
        e.preventDefault();
      }
    });
  }

  function initManageCopyLink() {
    // One-click copy of a manage-row share link (reuses the clipboard helper).
    document.addEventListener('click', async function(e) {
      const btn = e.target.closest('.manage-copy-link');
      if (!btn) return;
      const url = btn.dataset.shareUrl;
      if (!url) return;
      try {
        await navigator.clipboard.writeText(url);
        showToast('Link copied!');
        const original = btn.textContent;
        btn.textContent = 'Copied!';
        setTimeout(() => { btn.textContent = original; }, 2000);
      } catch (err) {
        showToast('Could not copy link', 'error');
      }
    });
  }

  // ==========================================================================
  // Auto-focus first input on RSVP form
  // ==========================================================================
  // ==========================================================================
  // F5 Carpool — driving toggle reveals details; needs_ride hides when driving
  // ==========================================================================
  function initCarpoolForm() {
    const driveToggle = document.getElementById('drivingToggle');
    const driveDetails = document.getElementById('driveDetails');
    const needsWrap = document.getElementById('needsRideToggleWrap');
    if (driveToggle && driveDetails) {
      driveToggle.addEventListener('change', () => {
        const driving = driveToggle.checked;
        driveDetails.hidden = !driving;
        if (needsWrap) {
          needsWrap.hidden = driving;
          if (driving) {
            const needsInput = needsWrap.querySelector('input[name="needs_ride"]');
            if (needsInput) needsInput.checked = false;
          }
        }
      });
    }
    // Mutual exclusion in both directions: needs_ride unchecks driving.
    if (needsWrap) {
      const needsInput = needsWrap.querySelector('input[name="needs_ride"]');
      if (needsInput) {
        needsInput.addEventListener('change', () => {
          if (needsInput.checked && driveToggle) {
            driveToggle.checked = false;
            if (driveDetails) driveDetails.hidden = true;
          }
        });
      }
    }
  }

  function initAutoFocus() {
    const nameInput = document.getElementById('attendeeName');
    if (nameInput) {
      // Focus without scrolling. A plain focus() makes the browser jump the
      // page down to the RSVP field on every open, which hides the cover
      // hero + details behind the sticky header ("double header" symptom).
      // preventScroll keeps focus (fast RSVP for returning users) without
      // yanking new visitors away from the event details.
      nameInput.focus({ preventScroll: true });
    }
  }

  // ==========================================================================
  // Utility
  // ==========================================================================
  function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  // First initial of the first + last word, uppercased — "Eric McLo" -> "EM".
  // These become the overlapping avatar chips on the attendee header.
  function initials(name) {
    const parts = String(name || '').trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return '?';
    const first = parts[0][0];
    const last = parts.length > 1 ? parts[parts.length - 1][0] : '';
    return (first + last).toUpperCase();
  }

  // Rebuild the avatar stack inside a card head. attendees = [{name,status}].
  // Only the people whose status is "going" get a face. Mirrors the server-side
  // render in adventure.html exactly (same order, same +N threshold).
  function renderAvatarStack(headEl, attendees) {
    if (!headEl) return;
    const AVATAR_LIMIT = 5;
    const going = attendees.filter(a => a.status === 'going');
    const visible = going.slice().reverse().slice(0, AVATAR_LIMIT);
    const extra = going.length - visible.length;

    const stack = document.createElement('div');
    stack.className = 'avatar-stack';
    stack.setAttribute('aria-label', going.length + (going.length === 1 ? ' person is' : ' people are') + ' going');

    visible.forEach(a => {
      const chip = document.createElement('span');
      chip.className = 'avatar';
      chip.textContent = initials(a.name);
      chip.title = a.name;
      stack.appendChild(chip);
    });
    if (extra > 0) {
      const chip = document.createElement('span');
      chip.className = 'avatar avatar-more';
      chip.textContent = '+' + extra;
      chip.title = extra + (extra === 1 ? ' more person going' : ' more people going');
      stack.appendChild(chip);
    }

    const old = headEl.querySelector('.avatar-stack');
    if (old) old.replaceWith(stack); else headEl.appendChild(stack);
  }

  // ==========================================================================
  // Initialize
  // ==========================================================================
  // Appearance panel — one header button opens a panel with Theme (3 pills)
  // and Color (15 swatches). Both persist per-browser in localStorage and
  // apply before first paint (see base.html head script). Mirrors the
  // [data-palette] overrides in static/palettes.css.
  const PALETTES = [
    { id: 'denim-dusk',     name: 'Denim Dusk', icon: '🌆', accent: '#3e5b6e', pale: '#e4ebf0' },
    { id: 'mossy-pine',     name: 'Mossy Pine', icon: '🌲', accent: '#3f5c33', pale: '#e3ead2' },
    { id: 'desert-sunrise', name: 'Desert Sunrise', icon: '🌵', accent: '#b4552d', pale: '#f6e2d3' },
    { id: 'alpine-lake',    name: 'Alpine Lake', icon: '🏔️', accent: '#35686b', pale: '#e0eceb' },
    { id: 'lupine-meadow',  name: 'Lupine Meadow', icon: '🦋', accent: '#6b5b8f', pale: '#eae5f2' },
    { id: 'peach-sorbet',   name: 'Peach Sorbet', icon: '🍑', accent: '#de6a49', pale: '#f9e2d6' },
    { id: 'blush-rose',     name: 'Blush Rose', icon: '🌹', accent: '#b4685f', pale: '#f4e3df' },
    { id: 'golden-hour',    name: 'Golden Hour', icon: '🌅', accent: '#a8711f', pale: '#f5e7c4' },
    { id: 'midnight-indigo',name: 'Midnight Indigo', icon: '🌌', accent: '#46508d', pale: '#e3e6f5' },
    { id: 'basalt-smoke',   name: 'Basalt Smoke', icon: '🪨', accent: '#5a635c', pale: '#e2e4e1' },
    { id: 'lavender-haze',  name: 'Lavender Haze', icon: '💜', accent: '#9a7bb0', pale: '#f0e7f4' },
    { id: 'pink-bloom',     name: 'Pink Bloom', icon: '🌷', accent: '#d6458c', pale: '#fbe3ee' }
  ];

  function initAppearancePanel() {
    const wrap = document.querySelector('.appearance-wrap');
    const toggle = document.querySelector('.appearance-toggle');
    const swatches = document.querySelector('.appearance-swatches');
    if (!wrap || !toggle || !swatches) return;

    // Build palette rows: one row per palette, small swatch dot on the left,
    // name on the right. Vertical list reads cleanly and removes the "icons
    // too big in a grid" pain point from the previous 5-column swatch grid.
    PALETTES.forEach(p => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'appearance-swatch';
      btn.setAttribute('role', 'radio');
      btn.dataset.palette = p.id;
      btn.innerHTML =
        '<span class="appearance-swatch-icon" aria-hidden="true">' + p.icon + '</span>' +
        '<span class="appearance-swatch-name">' + p.name + '</span>';
      btn.addEventListener('click', () => {
        selectPalette(p.id);
        syncState();
        // Keep the panel open so the user can see the change and keep
        // comparing. It closes on outside click or Escape (see below).
      });
      swatches.appendChild(btn);
    });

    // Theme pills.
    Array.from(document.querySelectorAll('.appearance-pill[data-theme-choice]')).forEach(pill => {
      pill.addEventListener('click', () => {
        selectTheme(pill.dataset.themeChoice);
        syncState();
      });
    });

    function syncState() {
      // Theme
      const choice = currentTheme();
      Array.from(document.querySelectorAll('.appearance-pill[data-theme-choice]')).forEach(pill => {
        pill.setAttribute('aria-checked', pill.dataset.themeChoice === choice ? 'true' : 'false');
      });
      // Palette
      const cur = currentPalette() || 'basalt-smoke';
      Array.from(swatches.children).forEach(s => {
        s.setAttribute('aria-checked', s.dataset.palette === cur ? 'true' : 'false');
      });
    }

    toggle.addEventListener('click', (e) => {
      e.stopPropagation();
      const open = wrap.classList.toggle('open');
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
    document.addEventListener('click', (e) => {
      if (!wrap.contains(e.target)) closePanel();
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') closePanel();
    });

    function closePanel() {
      wrap.classList.remove('open');
      toggle.setAttribute('aria-expanded', 'false');
    }

    syncState();
  }

  function currentTheme() {
    try {
      const v = localStorage.getItem('adventure-theme');
      if (v === 'light' || v === 'dark') return v;
      return 'system';
    } catch (e) { return 'system'; }
  }

  function selectTheme(choice) {
    const root = document.documentElement;
    try {
      if (choice === 'light') {
        root.dataset.theme = 'light';
        localStorage.setItem('adventure-theme', 'light');
      } else if (choice === 'dark') {
        root.dataset.theme = 'dark';
        localStorage.setItem('adventure-theme', 'dark');
      } else {
        // 'system' — clear attribute so CSS @media takes over.
        delete root.dataset.theme;
        localStorage.removeItem('adventure-theme');
      }
    } catch (e) {}
    syncThemeColor();
  }

  function currentPalette() {
    try { return localStorage.getItem('adventure-palette') || ''; }
    catch (e) { return ''; }
  }

  function selectPalette(id) {
    const root = document.documentElement;
    if (id === 'basalt-smoke') {
      // Basalt Smoke is the default — clearing the attribute keeps it in sync
      // with the no-picker look and avoids a redundant override.
      delete root.dataset.palette;
      try { localStorage.removeItem('adventure-palette'); } catch (e) {}
    } else {
      root.dataset.palette = id;
      try { localStorage.setItem('adventure-palette', id); } catch (e) {}
    }
    syncThemeColor();
    const label = PALETTES.find(x => x.id === id)?.name || 'Basalt Smoke';
    showToast('Color: ' + label, 'success');
  }

  function syncThemeColor() {
    // Keep the mobile browser chrome (address bar) on the palette accent.
    const accent = getComputedStyle(document.documentElement)
      .getPropertyValue('--denim').trim();
    if (accent) {
      let meta = document.querySelector('meta[name="theme-color"]');
      if (meta) meta.setAttribute('content', accent);
    }
  }

  // ==========================================================================
  // RSVP Name — localStorage auto-fill
  // ==========================================================================
  function initRsvpNameStorage() {
    const input = document.querySelector('input[data-rsvp-name]');
    if (!input) return;
    const shareId = input.dataset.shareId;
    if (!shareId) return;

    // Pre-fill if visitor has RSVP'd on this device before (for this adventure).
    try {
      const saved = localStorage.getItem('rsvp_name_' + shareId);
      if (saved && !input.value) input.value = saved;
    } catch (e) {}

    // Save name on submit so return visits skip re-typing.
    const form = input.closest('form');
    if (form) {
      form.addEventListener('submit', function() {
        try {
          if (input.value.trim()) {
            localStorage.setItem('rsvp_name_' + shareId, input.value.trim());
          }
        } catch (e) {}
      }, { once: true });
    }
  }

  // ==========================================================================
  // Packing List — localStorage persistence
  // ==========================================================================
  function initPackingList() {
    const list = document.querySelector('.packing-list[data-share-id]');
    if (!list) return;
    const shareId = list.dataset.shareId;
    if (!shareId) return;

    const STORAGE_KEY = 'packing_' + shareId;
    const checkboxes = list.querySelectorAll('input[data-packing-item]');
    if (!checkboxes.length) return;

    // Restore saved checked state.
    try {
      const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
      checkboxes.forEach(cb => {
        const idx = parseInt(cb.dataset.packingItem, 10);
        if (saved.includes(idx)) cb.checked = true;
      });
    } catch (e) {}

    // Save on every change.
    list.addEventListener('change', function() {
      const checked = Array.from(checkboxes)
        .filter(cb => cb.checked)
        .map(cb => parseInt(cb.dataset.packingItem, 10));
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(checked));
      } catch (e) {}
    });
  }

  function initAttendeeDelete() {
    // Roster "Remove friend" is a plain (non-AJAX) POST — guard it with a
    // confirm so a stray tap can't silently delete someone's RSVP.
    document.addEventListener('submit', (e) => {
      const form = e.target.closest('.attendee-delete-form');
      if (!form) return;
      if (!confirm(`Remove ${form.dataset.attendee || 'this person'} from the list?`)) {
        e.preventDefault();
      }
    });
  }

  // Add to Calendar — transparent popup overlay (not pushing page content down).
  // iOS users can pick .ics from the list to open native Calendar app directly.
  function initCalMenu() {
    const menu = document.getElementById('calMenu');
    const btn = document.getElementById('calMenuBtn');
    const pop = document.getElementById('calMenuPop');
    const backdrop = document.getElementById('calMenuBackdrop');
    if (!menu || !btn || !pop || !backdrop) return;

    function close() {
      pop.hidden = true;
      backdrop.hidden = true;
      btn.setAttribute('aria-expanded', 'false');
    }
    function open() {
      pop.hidden = false;
      backdrop.hidden = false;
      btn.setAttribute('aria-expanded', 'true');
    }

    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      if (pop.hidden) open(); else close();
    });

    // Click backdrop to close
    backdrop.addEventListener('click', close);

    document.addEventListener('click', (e) => {
      if (!menu.contains(e.target)) close();
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') close();
    });
  }

  function init() {
    initWizard();
    initCategoryPicker();
    initShareButton();
    initRsvpForms();
    initCreateForm();
    initDeleteForm();
    initManageDeleteForm();
    initManageCopyLink();
    initCarpoolForm();
    initCarpoolActions();
    initCostCard();
    initSplitsCard();
    initPackingCard();
    initWeatherStrip();
    initCollapsibles();
    initSeriesCancel();
    initAutoFocus();
    initAppearancePanel();
    initRsvpNameStorage();
    initPackingList();
    initAttendeeDelete();
    initCalMenu();
    syncThemeColor();

    // Show any flash messages from server-rendered page
    const flashes = document.querySelectorAll('.flash');
    flashes.forEach((flash, index) => {
      setTimeout(() => {
        showToast(flash.textContent, flash.classList.contains('flash-error') ? 'error' : 'success');
      }, index * 100);
    });
  }

  // Global keyboard shortcuts
  document.addEventListener('keydown', (e) => {
    // Enter to submit any form (but not in multi-line textareas)
    if (e.key === 'Enter' && e.target.matches('input, select')) {
      e.preventDefault();
      const form = e.target.closest('form');
      if (form) form.requestSubmit();
    }
    // Escape to close open popovers/dropdowns
    if (e.key === 'Escape') {
      const pop = document.getElementById('calMenuPop');
      const popBackdrop = document.getElementById('calMenuBackdrop');
      if (pop && !pop.hidden) {
        pop.hidden = true;
        popBackdrop.hidden = true;
        const btn = document.getElementById('calMenuBtn');
        if (btn) btn.setAttribute('aria-expanded', 'false');
      }
      const sharePop = document.getElementById('sharePopover');
      if (sharePop && !sharePop.hidden) {
        sharePop.hidden = true;
      }
    }
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();