"""Generate a pretty PNG share card for an adventure (Open Graph image).

Pillow + the bundled Karla/Fraunces fonts render a 1200x630 card (the standard
1.91:1 OG ratio) with the adventure name, date, location, and "X going" chip,
on a gradient tinted by the adventure's vibe. Pure server-side, no JS needed by
the sharing app.
"""
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

FONT_DIR = Path(__file__).parent / 'static' / 'fonts'

# vibe -> (top, bottom) gradient in the site's light-mode cover colors
VIBE_BG = {
    'hike':   ('#dde4d5', '#90a185'),
    'snow':   ('#dce6ee', '#93aec4'),
    'climb':  ('#e7ddd3', '#b3a390'),
    'paddle': ('#d8e6e4', '#8fb0ad'),
    'sport':  ('#dfe4e4', '#93a3a1'),
    'games':  ('#efe6d9', '#c6a985'),
    'food':   ('#efe6cd', '#c8b285'),
    'party':  ('#f0ded8', '#c5927f'),
}
DEFAULT_BG = ('#dfe4e4', '#93a3a1')

INK = '#1c1b18'          # main text (dark on light gradients)
SOFT = '#4a463f'         # secondary text
CHIP_INK = '#2f2c26'     # "X going" chip text
GLOW = '#2f4a3a'         # accent underline / eyebrow (deep green)

CARD_W, CARD_H = 1200, 630


def _hex(rgb):
    return tuple(int(rgb[i:i + 2], 16) for i in (1, 3, 5))


def _lerp(c1, c2, t):
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def _gradient(top, bottom, w, h):
    c1, c2 = _hex(top), _hex(bottom)
    img = Image.new('RGB', (w, h))
    px = img.load()
    for y in range(h):
        c = _lerp(c1, c2, y / (h - 1))
        for x in range(w):
            px[x, y] = c
    return img


def _font(name, size, weight='Regular'):
    f = ImageFont.truetype(str(FONT_DIR / f'{name}.ttf'), size)
    try:
        f.set_variation_by_axes([weight])
    except Exception:
        pass
    return f


def _wrap(draw, text, font, max_width):
    """Greedy word-wrap to fit max_width; returns list of lines."""
    words = text.split()
    if not words:
        return ['']
    lines, cur = [], ''
    for w in words:
        trial = (cur + ' ' + w).strip()
        if draw.textlength(trial, font=font) <= max_width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _letterspaced(draw, text, font, x, y, tracking, fill):
    """Draw text with manual letter tracking (for an eyebrow/all-caps look)."""
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += draw.textlength(ch, font=font) + tracking


def generate_card(name, when, location, going_text, vibe=None):
    """Return a PIL Image for the share card."""
    top, bottom = VIBE_BG.get(vibe or '', DEFAULT_BG)
    img = _gradient(top, bottom, CARD_W, CARD_H)
    d = ImageDraw.Draw(img)

    M = 76
    inner_w = CARD_W - 2 * M

    # Eyebrow (all-caps, tracked) — reads as a brand label.
    brow_font = _font('Karla', 30, 'Bold')
    _letterspaced(d, 'EVENT', brow_font, M, 78, 6, GLOW)

    # Adventure name — big, wrapped.
    # The card has fixed real estate: divider + 2 meta lines (when + location)
    # + the "X going" chip at the bottom. We pick a name size that lets
    # everything fit. Shrinks gracefully so a long name (or a 4-day Moab trip)
    # doesn't crash into the location/chip.
    name_font = _font('Fraunces', 118, 'SemiBold')
    meta_size = 44
    chip_top = CARD_H - 116
    M_TOP = 150
    DIVIDER_PAD = 6 + 20 + 56  # divider gap + divider height + space to meta
    while name_font.size > 48:
        cand_lines = _wrap(d, name, name_font, inner_w)
        if len(cand_lines) > 3 or any(d.textlength(l, font=name_font) > inner_w for l in cand_lines):
            name_font = _font('Fraunces', name_font.size - 6, 'SemiBold')
            continue
        # Check the meta block fits below the divider
        line_h = int(name_font.size * 1.06)
        block_bottom = M_TOP + line_h * len(cand_lines) + DIVIDER_PAD
        meta_bottom = block_bottom + (meta_size + 18) * 2
        if meta_bottom <= chip_top - 16:
            break  # fits
        name_font = _font('Fraunces', name_font.size - 6, 'SemiBold')
    name_lines = _wrap(d, name, name_font, inner_w)

    y = 150
    line_h = int(name_font.size * 1.06)
    for ln in name_lines:
        d.text((M, y), ln, font=name_font, fill=INK)
        y += line_h

    # Accent divider.
    d.rounded_rectangle((M, y + 6, M + 84, y + 20), radius=7, fill=GLOW)

    meta_y = y + 56
    meta_font = _font('Karla', meta_size, 'Medium')
    d.text((M, meta_y), when, font=meta_font, fill=SOFT)
    d.text((M, meta_y + meta_size + 18), location, font=meta_font, fill=SOFT)

    # "X going" chip near the bottom.
    chip_font = _font('Karla', 40, 'Bold')
    chip_w = d.textlength(going_text, font=chip_font) + 60
    chip_x, chip_y = M, chip_top
    d.rounded_rectangle((chip_x, chip_y, chip_x + chip_w, chip_y + 72),
                        radius=36, fill=(255, 255, 255))
    d.text((chip_x + 30, chip_y + 12), going_text, font=chip_font, fill=CHIP_INK)

    # Small Purbition mark bottom-right.
    mark_font = _font('Karla', 30, 'Bold')
    _letterspaced(d, 'PURBITION', mark_font, CARD_W - M - d.textlength('PURBITION', font=mark_font), CARD_H - 78, 2, SOFT)

    return img
