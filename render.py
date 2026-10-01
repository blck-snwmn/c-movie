"""Render the evolution of Claude and ChatGPT (2022.11 -> 2026.10) as a transit-map style MP4.

Each generation line grows from left to right on a fixed world canvas. The first generations
branch off the timeline axis; later ones branch off the previous generation's line.
Lines keep a fixed row per company in order of appearance, newer rows further out. When every
model of a generation is retired, the line turns gray and stays in its row, and that company's
camera pans outward so only live rows stay on screen.
Releases pop up as temporary cards and then leave a dot and a short name on the line.
The camera zooms in along time to follow the playhead, then pulls back at the end to reveal the
whole map including retired rows. Captions at the bottom explain key moments, and bars on the
timeline show the number of releases per month.

usage:
  uv run python render.py [out.mp4] [music.wav]   (default: out/claude_chatgpt_evolution.mp4, out/music.wav)
  uv run python render.py --preview SECONDS...    (writes out/previews/preview_<SECONDS>.png)
"""
import bisect
import calendar
import functools
import glob
import math
import os
import subprocess
import sys
import unicodedata

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

W, H, FPS = 1920, 1080, 30
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")

# ---------------------------------------------------------------- data
# Generation lines, oldest first per company. parents = lines it branches from ("axis" = timeline).
# end=None means still active. Rows are fixed in order of appearance (see the rows section).
# End dates: Claude = API retirement of the last model; OpenAI = removal of the last model from ChatGPT.
LINES = [
    dict(id="c1", lane="claude", name="Claude 1 系", color=(120, 72, 60), parents=["axis"],
         start="2023-03-14", end="2024-11-06", end_note="Claude 1 / Instant が API 終了"),
    dict(id="c2", lane="claude", name="Claude 2 系", color=(146, 84, 66), parents=["c1"],
         start="2023-07-11", end="2025-07-21", end_note="Claude 2 / 2.1 が API 終了"),
    dict(id="c3", lane="claude", name="Claude 3 系", color=(184, 100, 74), parents=["c2"],
         start="2024-03-04", end="2026-04-20", end_note="最後の Claude 3 Haiku が API 終了"),
    dict(id="c4", lane="claude", name="Claude 4 系", color=(226, 124, 88), parents=["c3"],
         start="2025-05-22", end=None),
    dict(id="c5", lane="claude", name="Claude 5 系", color=(255, 180, 142), parents=["c4"],
         start="2026-06-09", end=None),
    dict(id="g3", lane="openai", name="GPT-3.5 系", color=(40, 96, 84), parents=["axis"],
         start="2022-11-30", end="2024-07-18", end_note="GPT-4o mini に置き換え"),
    dict(id="g4", lane="openai", name="GPT-4 系", color=(34, 136, 110), parents=["g3"],
         start="2023-03-14", end="2026-06-27", end_note="最後の GPT-4.5 が ChatGPT から終了"),
    dict(id="o", lane="openai", name="o シリーズ", color=(72, 150, 200), parents=["g4"],
         start="2024-09-12", end="2026-08-26", end_note="最後の o3 が ChatGPT から終了"),
    dict(id="g5", lane="openai", name="GPT-5 系", color=(25, 200, 156), parents=["g4", "o"],
         start="2025-08-07", end=None),
    dict(id="g6", lane="openai", name="GPT-6 系", color=(130, 240, 204), parents=["g5"],
         start="2026-09-03", end=None),
]

# (line, date, card title, short name left on the line, note, kind)
# kind: gen = new generation (starts a line), major = flagship model, model = other (dot only)
RELEASES = [
    ("g3", "2022-11-30", "ChatGPT", "ChatGPT", "GPT-3.5 で公開", "gen"),
    ("g3", "2023-03-01", "ChatGPT API", None, "gpt-3.5-turbo", "model"),
    ("g4", "2023-03-14", "GPT-4", "GPT-4", "マルチモーダル対応", "gen"),
    ("c1", "2023-03-14", "Claude", "Claude", "Claude / Claude Instant", "gen"),
    ("c2", "2023-07-11", "Claude 2", "Claude 2", "100K コンテキスト", "gen"),
    ("g4", "2023-11-06", "GPT-4 Turbo", "Turbo", "128K コンテキスト", "major"),
    ("c2", "2023-11-21", "Claude 2.1", "2.1", "200K コンテキスト", "major"),
    ("c3", "2024-03-04", "Claude 3", "Opus 3", "Opus / Sonnet / Haiku", "gen"),
    ("g4", "2024-05-13", "GPT-4o", "4o", "音声・画像をネイティブに", "major"),
    ("c3", "2024-06-20", "Claude 3.5 Sonnet", "3.5 Sonnet", "Opus 超えを Sonnet で", "major"),
    ("g4", "2024-07-18", "GPT-4o mini", None, "GPT-3.5 の後継", "model"),
    ("o", "2024-09-12", "o1-preview", "o1-preview", "初の推論モデル", "gen"),
    ("c3", "2024-10-22", "3.5 Sonnet (新)", "Computer Use", "Computer Use 登場", "major"),
    ("o", "2024-12-05", "o1 / o1 pro", "o1", "推論モデル正式版", "major"),
    ("o", "2025-01-31", "o3-mini", None, "無料枠に推論モデル", "model"),
    ("c3", "2025-02-24", "Claude 3.7 Sonnet", "3.7", "初のハイブリッド推論", "major"),
    ("g4", "2025-02-27", "GPT-4.5", "4.5", "最大の非推論モデル", "major"),
    ("g4", "2025-04-14", "GPT-4.1", None, "1M コンテキスト", "model"),
    ("o", "2025-04-16", "o3 / o4-mini", "o3", "推論 × ツール利用", "major"),
    ("c4", "2025-05-22", "Claude 4", "Opus 4", "Opus 4 / Sonnet 4", "gen"),
    ("o", "2025-06-10", "o3-pro", None, "高信頼の推論", "model"),
    ("c4", "2025-08-05", "Opus 4.1", "4.1", "コーディング強化", "major"),
    ("g5", "2025-08-07", "GPT-5", "GPT-5", "GPT と o シリーズを統合", "gen"),
    ("g5", "2025-09-15", "GPT-5-Codex", None, "コーディング特化", "model"),
    ("c4", "2025-09-29", "Sonnet 4.5", "Sonnet 4.5", "エージェント性能向上", "major"),
    ("c4", "2025-10-15", "Haiku 4.5", None, "小型でも Computer Use", "model"),
    ("g5", "2025-11-12", "GPT-5.1", "5.1", "適応的推論", "major"),
    ("c4", "2025-11-24", "Opus 4.5", "4.5", "effort パラメータ", "major"),
    ("g5", "2025-12-11", "GPT-5.2", "5.2", "知的業務向け", "major"),
    ("c4", "2026-02-05", "Opus 4.6", "4.6", "1M コンテキスト", "major"),
    ("c4", "2026-02-17", "Sonnet 4.6", None, "Computer Use 強化", "model"),
    ("g5", "2026-03-05", "GPT-5.4", "5.4", "ネイティブ PC 操作", "major"),
    ("c4", "2026-04-16", "Opus 4.7", "4.7", "高解像度ビジョン", "major"),
    ("g5", "2026-04-23", "GPT-5.5", "5.5", "ChatGPT / Codex に展開", "major"),
    ("c4", "2026-05-28", "Opus 4.8", "4.8", "誠実さと信頼性", "major"),
    ("c5", "2026-06-09", "Claude 5", "Fable 5", "Fable 5 / Mythos 5", "gen"),
    ("c5", "2026-06-30", "Sonnet 5", None, "Opus 級を Sonnet 価格で", "model"),
    ("g5", "2026-07-09", "GPT-5.6", "5.6", "Sol / Terra / Luna", "major"),
    ("c5", "2026-07-24", "Opus 5", "Opus 5", "大幅な性能向上", "major"),
    ("c5", "2026-09-01", "Fable 5.1", None, "キャッシュ単価を削減", "model"),
    ("g6", "2026-09-03", "GPT-6", "Astra", "GPT-6 Astra", "gen"),
    ("c5", "2026-09-22", "Opus 5.5", "5.5", "Opus 5 比 40% 安価", "major"),
    ("g6", "2026-09-22", "GPT-6 Sol / Luna", None, "高速・低価格版", "model"),
    ("c5", "2026-09-28", "Sonnet 5.5", None, "30% 高速・価格据え置き", "model"),
    ("g6", "2026-09-29", "GPT-6.1 Sol", None, "Astra 級を 1/5 の価格で", "model"),
]
START = "2022-11-01"
TODAY = "2026-10-01"


def month_of(s):
    y, m, d = map(int, s.split("-"))
    return (y - 2025) * 12 + (m - 1) + (d - 1) / calendar.monthrange(y, m)[1]


# ---------------------------------------------------------------- style
BG = (13, 15, 20)
FG = (236, 238, 242)
MUTED = (128, 134, 148)
GRID = (40, 44, 54)
DEAD = (96, 100, 112)
LANES = {
    "claude": dict(color=(226, 124, 88), dir=-1, title="Anthropic", sub="Claude"),
    "openai": dict(color=(25, 200, 156), dir=1, title="OpenAI", sub="ChatGPT"),
}
AXIS_Y = 540
SPACING = 100          # distance between rows of the same company
P0, P1 = month_of(START) - 0.2, month_of(TODAY)
X_L, X_R = 200, 1650   # world x of P0 and P1 (today)
PXPM = (X_R - X_L) / (P1 - P0)
LINE_W = 5
SS = 2                 # supersampling factor for drawing lines


def X(m):
    return X_L + (m - P0) * PXPM


def font_path(weight):
    # macOS file names are NFD, so normalize before comparing
    want = f"角ゴシック W{weight}.ttc"
    for p in glob.glob("/System/Library/Fonts/*.ttc"):
        if unicodedata.normalize("NFC", p).endswith(want):
            return p
    raise FileNotFoundError(want)


_fonts = {}


def F(size, weight=6):
    key = (size, weight)
    if key not in _fonts:
        _fonts[key] = ImageFont.truetype(font_path(weight), size)
    return _fonts[key]


def mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def smooth(x):
    x = clamp(x)
    return x * x * (3 - 2 * x)


def ease_out_back(x):
    x = clamp(x)
    c = 1.9
    return 1 + (c + 1) * (x - 1) ** 3 + c * (x - 1) ** 2


# ---------------------------------------------------------------- sprites
def circle_sprite(r, color, ss=4):
    size = int(r * 2 + 4)
    img = Image.new("RGBA", (size * ss, size * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = size * ss / 2
    d.ellipse([c - r * ss, c - r * ss, c + r * ss, c + r * ss], fill=color + (255,))
    return img.resize((size, size), Image.LANCZOS)


def ring_sprite(r, color, width, ss=4):
    size = int(r * 2 + 4)
    img = Image.new("RGBA", (size * ss, size * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = size * ss / 2
    d.ellipse([c - r * ss, c - r * ss, c + r * ss, c + r * ss], fill=BG + (255,),
              outline=color + (255,), width=int(width * ss))
    return img.resize((size, size), Image.LANCZOS)


def glow_sprite(r, color, peak=110):
    size = r * 2
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    px = img.load()
    for y in range(size):
        for x in range(size):
            dist = ((x - r) ** 2 + (y - r) ** 2) ** 0.5 / r
            if dist < 1:
                px[x, y] = color + (int(peak * (1 - dist) ** 2),)
    return img


def _with_glow(card, color, strength, pad=16):
    w, h = card.size
    out = Image.new("RGBA", (w + pad * 2, h + pad * 2), color + (0,))
    glow = Image.new("RGBA", out.size, color + (0,))
    ImageDraw.Draw(glow).rounded_rectangle([pad, pad, pad + w, pad + h], radius=12, fill=color + (strength,))
    out.alpha_composite(glow.filter(ImageFilter.GaussianBlur(10)))
    out.alpha_composite(card, (pad, pad))
    return out, pad


def _rounded(w, h, fill, outline, width, radius=10, ss=2):
    img = Image.new("RGBA", (w * ss, h * ss), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle([0, 0, w * ss - 1, h * ss - 1], radius=radius * ss,
                                          fill=fill + (255,), outline=outline + (255,), width=width * ss)
    return img.resize((w, h), Image.LANCZOS)


def card_sprite(e, color):
    """Return (sprite, offset from the sprite's top-left to the card body)."""
    kind, name, date = e["kind"], e["name"], e["date"]
    sub = f"{date[:4]}/{date[5:7]}/{date[8:10]}  {e['note']}"
    # dark generation colors are hard to read, so lighten them on cards
    color = mix(color, FG, 0.15)
    if kind == "gen":
        f_k, f_t, f_s = F(15, 7), F(50, 9), F(18, 4)
        kicker = "NEW GENERATION"
        kw = sum(f_k.getlength(ch) * 1.25 for ch in kicker)
        w = int(max(f_t.getlength(name), f_s.getlength(sub), kw)) + 36
        h = 112
        card = _rounded(w, h, mix(BG, color, 0.22), color, 3, radius=12)
        d = ImageDraw.Draw(card)
        kx = 18
        for ch in kicker:
            d.text((kx, 12), ch, font=f_k, fill=color)
            kx += f_k.getlength(ch) * 1.25
        d.text((18, 30), name, font=f_t, fill=(255, 255, 255))
        d.text((18, 84), sub, font=f_s, fill=mix(color, FG, 0.45))
        return _with_glow(card, color, 150)
    if kind == "major":
        f1, f2 = F(26, 7), F(16, 4)
        w = int(max(f1.getlength(name), f2.getlength(sub))) + 28
        card = _rounded(w, 52, mix(BG, color, 0.25), color, 2)
        d = ImageDraw.Draw(card)
        d.text((14, 3), name, font=f1, fill=(255, 255, 255))
        d.text((14, 32), sub, font=f2, fill=mix(color, FG, 0.4))
        return _with_glow(card, color, 70)
    f1, f2 = F(21, 6 if kind == "end" else 5), F(15, 3)
    w = int(max(f1.getlength(name), f2.getlength(sub))) + 24
    if kind == "end":
        card = _rounded(w, 46, (26, 28, 34), (96, 100, 112), 1)
        name_c, sub_c = (180, 184, 194), MUTED
    else:
        card = _rounded(w, 46, mix(BG, color, 0.08), mix(BG, color, 0.45), 1)
        name_c, sub_c = (205, 208, 216), mix(color, MUTED, 0.4)
    d = ImageDraw.Draw(card)
    d.text((12, 3), name, font=f1, fill=name_c)
    d.text((12, 27), sub, font=f2, fill=sub_c)
    return card, 0


def with_alpha(img, a):
    if a >= 0.999:
        return img
    r, g, b, al = img.split()
    al = al.point(lambda v: int(v * a))
    return Image.merge("RGBA", (r, g, b, al))


def paste(frame, sprite, x, y, a=1.0):
    if a <= 0.001:
        return
    frame.alpha_composite(with_alpha(sprite, a), (int(x), int(y)))


# ---------------------------------------------------------------- build model
lines = {}
for order, L in enumerate(LINES):
    L = dict(L)
    L["order"] = order
    L["dir"] = LANES[L["lane"]]["dir"]
    L["ms"] = month_of(L["start"])
    L["me"] = month_of(L["end"]) if L["end"] else 99.0
    lines[L["id"]] = L

events = []
for lid, date, name, short, note, kind in RELEASES:
    events.append(dict(line=lid, m=month_of(date), date=date, name=name, short=short, note=note, kind=kind))
for L in lines.values():
    if L["end"]:
        events.append(dict(line=L["id"], m=L["me"], date=L["end"], name=f"{L['name']} 提供終了",
                           short=None, note=L["end_note"], kind="end"))
events.sort(key=lambda e: e["m"])
for e in events:
    L = lines[e["line"]]
    e["sprite"], e["pad"] = card_sprite(e, L["color"])
    e["x"] = X(e["m"])
    if e["kind"] == "gen":
        e["short"] = L["name"]                # leave the line name at its start
        e["lx"] = X(e["m"] + 0.9)
    else:
        e["lx"] = e["x"]

DOT_R = {"gen": 10, "major": 7, "model": 5}
DOT = {lid: {kind: ring_sprite(r, L["color"], 3 if kind != "model" else 2.2) for kind, r in DOT_R.items()}
       for lid, L in lines.items()}
END_CAP = ring_sprite(7, (130, 134, 146), 2.6)
HEAD = {lid: circle_sprite(7, mix(L["color"], FG, 0.1)) for lid, L in lines.items()}
HEAD_GLOW = {lid: glow_sprite(34, L["color"], 150) for lid, L in lines.items()}
GLOW_BIG = {lid: glow_sprite(120, mix(L["color"], FG, 0.15), 120) for lid, L in lines.items()}
GLOW = {lid: glow_sprite(46, L["color"], 110) for lid, L in lines.items()}

# ---------------------------------------------------------------- timing
T_INTRO = 3.5
T_MAIN = 80.0
T_HOLD = 0.6
T_ZOOM = 2.8           # duration of the final camera pull-back
T_OUTRO = 6.5
T_FADE = 1.2
TOTAL = T_INTRO + T_MAIN + T_HOLD + T_ZOOM + T_OUTRO + T_FADE
T_REVEAL = T_INTRO + T_MAIN + T_HOLD
CARD_LIFE = {"gen": 3.2, "major": 2.4, "model": 1.7, "end": 2.6}


def _dwell(m):
    """Relative screen time spent on month m: longer around releases, longest around new generations."""
    v = 0.3
    for e in events:
        v += 0.5 * math.exp(-(((m - e["m"]) / 0.5) ** 2))
        if e["kind"] == "gen":
            v += 1.1 * math.exp(-(((m - e["m"] - 0.3) / 0.5) ** 2))
    v *= 1 + 1.5 * max(0.0, 1 - (m - P0) / 0.8) + 2.0 * max(0.0, 1 - (P1 - m) / 1.0)
    return v


_N = 8000
_ms = [P0 + (P1 - P0) * i / _N for i in range(_N + 1)]
_ts = [0.0]
for i in range(1, _N + 1):
    _ts.append(_ts[-1] + (_ms[i] - _ms[i - 1]) * _dwell(_ms[i]))
_ts = [T_INTRO + T_MAIN * t / _ts[-1] for t in _ts]


def playhead(t):
    if t <= _ts[0]:
        return P0
    if t >= _ts[-1]:
        return P1
    i = bisect.bisect_right(_ts, t)
    t0, t1 = _ts[i - 1], _ts[i]
    return _ms[i - 1] + (_ms[i] - _ms[i - 1]) * (t - t0) / (t1 - t0)


def time_at(m):
    return _ts[min(bisect.bisect_left(_ms, m), _N)]


for e in events:
    e["tc"] = time_at(e["m"])
for L in lines.values():
    L["t_end"] = time_at(L["me"]) if L["end"] else 1e9
for i, e in enumerate(events):
    life = CARD_LIFE[e["kind"]]
    lane = lines[e["line"]]["lane"]
    # collapse a card early when the next release on the same line or a new generation of the same company arrives
    for f in events[i + 1:]:
        if f["line"] == e["line"] or (f["kind"] == "gen" and lines[f["line"]]["lane"] == lane):
            life = max(0.8, min(life, f["tc"] - e["tc"] - 0.1))
            break
    e["life"] = life


# ---------------------------------------------------------------- rows
# Each line gets a fixed row per company in order of appearance, from the axis outward.
# Retired lines turn gray and stay in their row; the company's camera pans them out of view behind the axis.
SLOT0 = 100            # world distance from the axis to the first row
HIDE_DELAY = 1.5       # seconds between a retirement and the camera starting to pan
PAN_T = 1.1            # seconds to pan a retired row out of view

for lane in LANES:
    for slot, L in enumerate(sorted((L for L in lines.values() if L["lane"] == lane), key=lambda L: L["ms"])):
        L["slot"] = slot
for L in lines.values():
    L["dist"] = SLOT0 + L["slot"] * SPACING            # distance from the axis (positive outward)
    L["t_start"] = time_at(L["ms"])

# Only rows retired contiguously from the axis outward can be hidden. A row starts hiding HIDE_DELAY after
# it and every row inside it have retired.
for lane in LANES:
    t_prev = -1e9
    for L in sorted((L for L in lines.values() if L["lane"] == lane), key=lambda L: L["slot"]):
        if not L["end"]:
            break
        L["t_hide"] = max(L["t_end"] + HIDE_DELAY, t_prev + PAN_T * 0.6)
        t_prev = L["t_hide"]


def pan_at(lane, t):
    """How far (world distance) the company's camera has panned outward."""
    return sum(SPACING * smooth((t - L["t_hide"]) / PAN_T)
               for L in lines.values() if L["lane"] == lane and "t_hide" in L)


CURVE_M = 0.9           # length of a branch curve, in months


def parent_dist(pid):
    return 0.0 if pid == "axis" else lines[pid]["dist"]


def point_dist(L, m, pid=None):
    """Distance from the axis of line L at month m, including the branch curve."""
    if m >= L["ms"] + CURVE_M:
        return L["dist"]
    pd = parent_dist(pid or L["parents"][0])
    return pd + (L["dist"] - pd) * smooth((m - L["ms"]) / CURVE_M)


# Place short names per line: outside first, inside if that overlaps
_placed = {}
for e in events:
    if not e["short"]:
        continue
    L = lines[e["line"]]
    w = F(14, 6).getlength(e["short"])
    x0, x1 = e["lx"] - w / 2 - 4, e["lx"] + w / 2 + 4
    for side in ("out", "in"):
        spans = _placed.setdefault((L["id"], side), [])
        if all(x1 < a or x0 > b for a, b in spans):
            spans.append((x0, x1))
            e["side"] = side
            break
    else:
        print(f"warning: short label dropped {e['short']}", file=sys.stderr)
        e["short"] = None


# ---------------------------------------------------------------- captions
# (date, color group, caption). Shown at the bottom when the playhead reaches the date.
CAPTIONS = [
    ("2022-11-30", "openai", "ChatGPT 公開 — 対話 AI ブームの始まり"),
    ("2023-03-14", "both", "GPT-4 と Claude が同じ日に登場"),
    ("2023-07-11", "claude", "Claude 2 と同時に claude.ai（ベータ）が公開"),
    ("2024-03-04", "claude", "Claude 3 世代：Opus / Sonnet / Haiku の 3 サイズ展開"),
    ("2024-05-13", "openai", "GPT-4o：音声・画像をネイティブに扱うモデルへ"),
    ("2024-07-18", "openai", "GPT-3.5 系が引退し、系譜は GPT-4 系へ"),
    ("2024-09-12", "openai", "o1-preview：「考えてから答える」推論モデルが登場"),
    ("2024-10-22", "claude", "Computer Use：AI が PC を操作し始める"),
    ("2025-02-24", "claude", "Claude 3.7 Sonnet：通常応答と推論をひとつのモデルに"),
    ("2025-05-22", "claude", "Claude 4 世代へ"),
    ("2025-08-07", "openai", "GPT-5：GPT と o シリーズがひとつに"),
    ("2025-11-12", "both", "リリースは加速し、1〜2 か月ごとに新モデルが出る時代へ"),
    ("2026-06-09", "claude", "Claude 5 世代：Fable / Mythos クラスが登場"),
    ("2026-06-27", "openai", "GPT-4 系が ChatGPT から引退"),
    ("2026-09-03", "openai", "GPT-6 Astra 登場"),
]
captions = [dict(t=time_at(month_of(d)), lane=lane, text=txt, date=d) for d, lane, txt in CAPTIONS]
for i, c in enumerate(captions):
    nxt = captions[i + 1]["t"] if i + 1 < len(captions) else T_REVEAL
    c["end"] = min(c["t"] + 4.2, nxt - 0.15)

# Releases per month (for the bars on the timeline)
MONTHS = {}
for e in events:
    if e["kind"] == "end":
        continue
    MONTHS.setdefault((lines[e["line"]]["lane"], math.floor(e["m"])), []).append(e["tc"])


# ---------------------------------------------------------------- camera
# Horizontally (time) a shared camera shows a few months and follows the playhead.
# Vertically the axis stays put and each company has its own outward pan and vertical zoom.
# Panning sends retired rows behind the axis so only live rows show; the end pulls back to show every row.
AXIS_SCREEN = 545          # screen y of the axis during the main part
FINAL_AY = 480             # screen y of the axis in the final overview (raised to make room for the summary)
FINAL_TOP = 150            # screen y of the topmost row in the final overview
HALF = 400                 # height from the axis to the screen edge (below the header / above captions)
CARD_ROOM = 140            # room kept outside the outermost row for cards
FINAL_ZX = 1.08
FINAL_CX = 975.0
PH_SCREEN = 0.62           # playhead position on screen, as a fraction of the width


def _window_months(p):
    """Number of months on screen: 8 at the start, 14 near the end."""
    return 8 + 6 * smooth((p - P0) / (P1 - P0))


def _cx_for(p, zx):
    cx = X(p) - (PH_SCREEN * W - W / 2) / zx
    return max(cx, X(P0) - 60 + (W / 2) / zx)   # don't show the empty area before the start


def _lane_zy(lane, t, p):
    """Vertical zoom that fits the live rows (including ones about to be born) plus cards."""
    pan = pan_at(lane, t)
    outer = max([L["dist"] for L in lines.values()
                 if L["lane"] == lane and L["ms"] <= p + 1.2] + [SLOT0])
    return clamp((HALF - CARD_ROOM) / max(outer - pan, SLOT0), 0.8, 1.7)


def _final_zy():
    # use one zoom for both companies so row spacing matches
    outer = max(L["dist"] for L in lines.values())
    return (FINAL_AY - FINAL_TOP) / outer


def _build_camera():
    n = int(TOTAL * FPS) + 2
    raw = []
    for i in range(n):
        t = i / FPS
        p = playhead(t)
        zx = W / (_window_months(p) * PXPM)
        zy = {lane: _lane_zy(lane, t, p) for lane in LANES}
        pan = {lane: pan_at(lane, t) for lane in LANES}
        raw.append([zx, zy, pan])
    # Gaussian-smooth the vertical zoom so new rows don't jolt the view
    rad = int(0.8 * FPS)
    ker = [math.exp(-((j / (rad / 2)) ** 2)) for j in range(-rad, rad + 1)]
    ksum = sum(ker)
    sm = []
    for i in range(n):
        zy = {}
        for lane in LANES:
            zy[lane] = sum(raw[min(max(i + j - rad, 0), n - 1)][1][lane] * w_ for j, w_ in enumerate(ker)) / ksum
        sm.append(zy)
    out = []
    i_rev = int(T_REVEAL * FPS)
    for i in range(n):
        t = i / FPS
        zx, _, pan = raw[i]
        zy = sm[i]
        ay = AXIS_SCREEN
        if t <= T_REVEAL:
            cx = _cx_for(playhead(t), zx)
        else:
            # finale: pull back to the full timeline and every row, bringing hidden rows back
            k = smooth((t - T_REVEAL) / T_ZOOM)
            zx0, zy0, pan0 = raw[i_rev][0], sm[i_rev], raw[i_rev][2]
            cx0 = _cx_for(P1, zx0)
            zx = math.exp(math.log(zx0) + (math.log(FINAL_ZX) - math.log(zx0)) * k)
            cx = cx0 + (FINAL_CX - cx0) * k
            zy = {lane: zy0[lane] + (_final_zy() - zy0[lane]) * k for lane in LANES}
            pan = {lane: pan0[lane] * (1 - k) for lane in LANES}
            ay = AXIS_SCREEN + (FINAL_AY - AXIS_SCREEN) * k
        out.append((cx, zx, zy, pan, ay))
    return out


CAM = _build_camera()
_cam = {"cx": W / 2, "zx": 1.0, "zy": {k: 1.0 for k in LANES}, "pan": {k: 0.0 for k in LANES},
        "ay": AXIS_SCREEN}


def set_camera(t):
    cx, zx, zy, pan, ay = CAM[min(int(round(t * FPS)), len(CAM) - 1)]
    _cam.update(cx=cx, zx=zx, zy=zy, pan=pan, ay=ay)


def AY():
    """Screen y of the axis."""
    return _cam["ay"]


def SX(wx):
    return (wx - _cam["cx"]) * _cam["zx"] + W / 2


def SYD(lane, dist):
    """Map a world distance from the axis for company `lane` to screen y."""
    ln = LANES[lane]
    return AY() + ln["dir"] * (dist - _cam["pan"][lane]) * _cam["zy"][lane]


def U(lane):
    """Scale for on-screen text and line widths (larger when zoomed in)."""
    return clamp(_cam["zy"][lane] ** 0.6 * 1.08, 1.0, 1.5)


# ---------------------------------------------------------------- drawing
def dead_k(L, t):
    """0 = active, 1 = retired and fully faded to gray."""
    return smooth((t - L["t_end"]) / 1.0)


def line_color(L, t):
    return mix(L["color"], DEAD, 0.5 * dead_k(L, t))


def draw_pace(d, t, p):
    """Draw releases per month as bars along the axis (above = Anthropic, below = OpenAI).
    Each bar sits in its month's slot and is clipped at the playhead."""
    xp = SX(X(p))
    for (lane, mi), tcs in MONTHS.items():
        n = sum(1 for tc in tcs if tc <= t)
        if n == 0:
            continue
        last = max(tc for tc in tcs if tc <= t)
        grow = n - 1 + ease_out_back((t - last) / 0.5)
        x0 = SX(X(mi)) + 2
        x1 = min(SX(X(mi + 1)) - 2, xp)
        if x1 <= x0:
            continue
        h = grow * 9
        col = mix(BG, LANES[lane]["color"], 0.32)
        if lane == "claude":
            d.rectangle([x0, AY() - 3 - h, x1, AY() - 3], fill=col)
        else:
            d.rectangle([x0, AY() + 3, x1, AY() + 3 + h], fill=col)


def draw_axis(d, p):
    """Draw the axis and ticks; the future side is shown faintly."""
    ay = AY()
    xp = SX(X(p))
    d.line([(SX(X(P0) - 40), ay), (xp, ay)], fill=(92, 97, 110), width=3)
    for x in range(int(xp), int(SX(X(P1) + 50)), 14):
        d.line([(x, ay), (x + 6, ay)], fill=GRID, width=2)
    every_month = PXPM * _cam["zx"] > 55  # label every month when zoomed in enough
    for mi in range(math.ceil(P0), int(P1) + 2):
        x = SX(X(mi))
        if x < -80 or x > W + 80:
            continue
        future = mi > p
        y, mo = 2025 + mi // 12, mi % 12 + 1
        col = mix(MUTED, BG, 0.65) if future else MUTED
        if mo == 1:
            d.line([(x, ay - 12), (x, ay + 12)], fill=col, width=3)
            d.text((x + 6, ay - 36), str(y), font=F(26, 7), fill=mix(FG, BG, 0.65) if future else FG,
                   stroke_width=3, stroke_fill=BG)
        elif mo in (4, 7, 10) or every_month:
            d.line([(x, ay - 6), (x, ay + 6)], fill=col, width=2)
            d.text((x + 3, ay + 9), f"{mo}月", font=F(16, 4), fill=col, stroke_width=2, stroke_fill=BG)
        else:
            d.line([(x, ay - 3), (x, ay + 3)], fill=col, width=1)


def _lane_lines(lane, t):
    # draw retired lines first so live lines pass over them
    return sorted((L for L in lines.values() if L["lane"] == lane), key=lambda L: (t < L["t_end"], L["slot"]))


def draw_lines(layer, lane, t, p):
    """Draw generation lines (supersampled for smooth curves)."""
    big = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    u = U(lane)
    for L in _lane_lines(lane, t):
        if p <= L["ms"]:
            continue
        col = line_color(L, t)
        width = max(2, int((LINE_W - 1.5 * dead_k(L, t)) * u * SS))
        m_to = min(p, L["me"])
        m_c = min(m_to, L["ms"] + CURVE_M)
        for pid in L["parents"]:
            n = 30
            pts = [(SX(X(m)) * SS, SYD(lane, point_dist(L, m, pid)) * SS)
                   for m in (L["ms"] + (m_c - L["ms"]) * i / n for i in range(n + 1))]
            d.line(pts, fill=col + (255,), width=width, joint="curve")
        if m_to > L["ms"] + CURVE_M:
            y = SYD(lane, L["dist"]) * SS
            d.line([(SX(X(m_c)) * SS, y), (SX(X(m_to)) * SS, y)], fill=col + (255,), width=width)
    layer.alpha_composite(big.reduce(SS))


def event_xy(e):
    """Screen position of an event's dot."""
    L = lines[e["line"]]
    if e["kind"] == "gen":
        # a new generation's dot sits at the branch point on its parent line
        return SX(e["x"]), SYD(L["lane"], parent_dist(L["parents"][0]))
    return SX(e["x"]), SYD(L["lane"], point_dist(L, e["m"]))


def draw_dots(layer, d, lane, t):
    for e in sorted(events, key=lambda e: t < lines[e["line"]]["t_end"]):
        L = lines[e["line"]]
        age = t - e["tc"]
        if L["lane"] != lane or age < 0:
            continue
        x, y = event_xy(e)
        if x < -150 or x > W + 150:
            continue
        if e["kind"] == "end":
            if ease_out_back(age / 0.4) > 0.05:
                paste(layer, END_CAP, x - END_CAP.width / 2, y - END_CAP.height / 2)
            continue
        if e["kind"] in ("gen", "major"):
            gen = e["kind"] == "gen"
            dur = 2.2 if gen else 1.2
            if age < dur:
                g = (GLOW_BIG if gen else GLOW)[L["id"]]
                paste(layer, g, x - g.width / 2, y - g.height / 2, 1 - age / dur)
                ring_col = mix(L["color"], FG, 0.2)
                for k in range(2 if gen else 1):
                    ak = age - k * 0.25
                    if 0 <= ak < dur - 0.3:
                        uu = ak / (dur - 0.3)
                        r = 10 + uu * (100 if gen else 50)
                        d.ellipse([x - r, y - r, x + r, y + r],
                                  outline=ring_col + (int(220 * (1 - uu) ** 1.5),), width=3)
        spr = DOT[L["id"]][e["kind"]]
        s = ease_out_back(age / 0.4) * (0.9 + 0.3 * (U(lane) - 1))
        if s > 0.05:
            sp = spr if abs(s - 1) < 0.001 else spr.resize((max(1, int(spr.width * s)),) * 2, Image.LANCZOS)
            paste(layer, sp, x - sp.width / 2, y - sp.height / 2, 1 - 0.3 * dead_k(L, t))


def draw_short_labels(d, lane, t, p):
    """Short names that stay on the line after a card collapses."""
    u = U(lane)
    f = F(round(14 * u), 6)
    for e in events:
        L = lines[e["line"]]
        if L["lane"] != lane or not e["short"]:
            continue
        k = smooth((t - e["tc"] - e["life"] + 0.2) / 0.5)
        lx = SX(e["lx"])
        if e["kind"] == "gen" and L["ms"] <= p < L["me"]:
            # show the line name at the start only once it is far enough from the tip label
            k *= smooth((SX(X(p)) - lx - 180) / 120)
        if k <= 0 or lx < -100 or lx > W + 100:
            continue
        w = f.getlength(e["short"])
        up = (L["dir"] < 0) == (e["side"] == "out")
        ly = SYD(lane, point_dist(L, e["m"] + (0.9 if e["kind"] == "gen" else 0)))
        y = ly - 25 * u if up else ly + 9 * u
        col = mix(mix(L["color"], FG, 0.4), DEAD, 0.45 * dead_k(L, t))
        d.text((lx - w / 2, y), e["short"], font=f, fill=mix(BG, col, k), stroke_width=3, stroke_fill=BG)


def draw_heads(layer, d, lane, t, p, z):
    """Glowing tip and its moving line name; retired lines keep their name at the end point."""
    u = U(lane)
    for L in lines.values():
        if L["lane"] != lane or p < L["ms"]:
            continue
        if p < L["me"]:
            hx, hy = SX(X(p)), SYD(lane, point_dist(L, p))
            k = smooth((p - L["ms"]) / 0.4)
            g = HEAD_GLOW[L["id"]]
            paste(layer, g, hx - g.width / 2, hy - g.height / 2, 0.9 * k * (1 - 0.5 * z))
            paste(layer, HEAD[L["id"]], hx - HEAD[L["id"]].width / 2, hy - HEAD[L["id"]].height / 2, k)
            d.text((hx + 14, hy - 11 * u), L["name"], font=F(round(18 * u), 7),
                   fill=mix(BG, mix(L["color"], FG, 0.35), k), stroke_width=3, stroke_fill=BG)
        else:
            x, y = SX(X(L["me"])) + 12, SYD(lane, L["dist"])
            k = dead_k(L, t)
            d.text((x, y - 9 * u), f"{L['name']} · 提供終了", font=F(round(14 * u), 5),
                   fill=mix(BG, (140, 144, 156), k), stroke_width=3, stroke_fill=BG)


def draw_cards(layer, d, lane, t):
    for e in events:
        L = lines[e["line"]]
        age = t - e["tc"]
        life = e["life"]
        if L["lane"] != lane or not 0 <= age < life + 0.35:
            continue
        a = smooth(age / 0.3) * (1 - smooth((age - life) / 0.35))
        spr, pad = e["sprite"], e["pad"]
        cw, ch = spr.width - 2 * pad, spr.height - 2 * pad
        x, y0 = event_xy(e)
        # place a new generation's card outside the new line's row
        y = SYD(lane, L["dist"]) if e["kind"] == "gen" else y0
        cx = max(20, min(x - 18, W - 30 - cw))
        drift = (1 - smooth(age / 0.3)) * 14 + smooth((age - life) / 0.35) * 18
        gap = 16
        if L["dir"] < 0:
            cy = y - gap - ch + drift
            stem = (cy + ch, y0)
        else:
            cy = y + gap - drift
            stem = (y0, cy)
        stem_col = (110, 114, 126) if e["kind"] == "end" else mix(L["color"], FG, 0.15)
        d.line([(x, stem[0]), (x, stem[1])], fill=stem_col + (int(220 * a),), width=2)
        paste(layer, spr, cx - pad, cy - pad, a)


def _lane_mask(lane):
    """Mask that hides content crossing the axis (hidden rows), fading out just before the axis."""
    # Built 2H tall with the axis at y = H; cropped at the current axis position when used.
    m = Image.new("L", (W, 2 * H), 0)
    d = ImageDraw.Draw(m)
    fade0, fade1 = 18, 58                     # fade between these distances from the axis
    for y in range(2 * H):
        dist = (H - y) if lane == "claude" else (y - H)
        v = int(255 * smooth((dist - fade0) / (fade1 - fade0)))
        if v:
            d.line([(0, y), (W, y)], fill=v)
    return m


LANE_MASK = {lane: _lane_mask(lane) for lane in LANES}


def draw_lane(frame, lane, t, p, z):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw_lines(layer, lane, t, p)
    d = ImageDraw.Draw(layer)
    draw_dots(layer, d, lane, t)
    draw_short_labels(d, lane, t, p)
    draw_heads(layer, d, lane, t, p, z)
    draw_cards(layer, d, lane, t)
    # hidden rows come back in the final overview, so the mask fades away
    top = int(round(H - AY()))
    mask = LANE_MASK[lane].crop((0, top, W, top + H))
    if z > 0:
        mask = Image.blend(mask, Image.new("L", (W, H), 255), z)
    layer.putalpha(ImageChops.multiply(layer.getchannel("A"), mask))
    frame.alpha_composite(layer)


def draw_playhead(d, p, z):
    a = 1 - z
    if a < 0.02:
        return
    x = SX(X(p))
    d.line([(x, 130), (x, 950)], fill=mix(BG, (255, 255, 255), 0.13 * a), width=2)


def draw_edges(frame):
    frame.alpha_composite(LEFT_FADE, (0, 0))


def _hgrad(w):
    img = Image.new("RGBA", (w, H), BG + (0,))
    px = img.load()
    for x in range(w):
        a = int(255 * (1 - x / w) ** 1.5)
        for y in range(H):
            px[x, y] = BG + (a,)
    return img


LEFT_FADE = _hgrad(130)


def draw_header(d, p, z):
    d.text((60, 44), "Claude × ChatGPT", font=F(40, 8), fill=FG)
    d.text((60 + F(40, 8).getlength("Claude × ChatGPT") + 20, 58), "進化の軌跡", font=F(28, 4), fill=MUTED)
    mi = math.floor(clamp(p, month_of(START), P1))
    txt = f"{2025 + mi // 12}年 {mi % 12 + 1:>2}月"
    f = F(54, 8)
    d.text((W - 60 - f.getlength(txt), 30), txt, font=f, fill=mix(BG, FG, 1 - 0.6 * z))


def draw_lane_titles(d):
    ay = AY()
    d.text((40, ay - 70), "Anthropic", font=F(20, 7), fill=LANES["claude"]["color"], stroke_width=4, stroke_fill=BG)
    d.text((40, ay + 44), "OpenAI", font=F(20, 7), fill=LANES["openai"]["color"], stroke_width=4, stroke_fill=BG)


def draw_legend(d, z):
    a = 1 - z
    if a < 0.02:
        return
    y = 1040
    x = 40
    for lane in ("claude", "openai"):
        d.rectangle([x, y + 4, x + 12, y + 16], fill=mix(BG, LANES[lane]["color"], 0.30 + 0.3 * a))
        x += 18
    d.text((x + 4, y), "時間軸の棒 = 月ごとのリリース数（上: Anthropic / 下: OpenAI）", font=F(15, 4),
           fill=mix(BG, MUTED, a))


def draw_caption(frame, d, t):
    """Caption at the bottom of the screen."""
    for c in captions:
        if not c["t"] <= t < c["end"] + 0.35:
            continue
        a = smooth((t - c["t"]) / 0.35) * (1 - smooth((t - c["end"]) / 0.35))
        rise = (1 - smooth((t - c["t"]) / 0.35)) * 12
        f_t, f_d = F(34, 7), F(20, 5)
        date = c["date"].replace("-", ".")
        wd = f_d.getlength(date)
        wt = f_t.getlength(c["text"])
        x0 = (W - (wd + 28 + wt)) / 2
        y = 972 + rise
        if c["lane"] == "both":
            cols = [LANES["claude"]["color"], LANES["openai"]["color"]]
        else:
            cols = [LANES[c["lane"]]["color"]]
        # date chip
        chip = Image.new("RGBA", (int(wd + 24), 34), (0, 0, 0, 0))
        cd = ImageDraw.Draw(chip)
        cd.rounded_rectangle([0, 0, chip.width - 1, 33], radius=17, fill=mix(BG, cols[0], 0.25) + (255,),
                             outline=cols[0] + (255,), width=2)
        if len(cols) == 2:
            cd.rounded_rectangle([chip.width // 2, 0, chip.width - 1, 33], radius=17,
                                 fill=mix(BG, cols[1], 0.25) + (255,), outline=cols[1] + (255,), width=2)
            cd.rectangle([chip.width // 2 - 2, 2, chip.width // 2 + 8, 31], fill=mix(BG, cols[1], 0.25) + (255,))
        cd.text((12, 5), date, font=f_d, fill=FG)
        paste(frame, chip, x0 - 12, y + 6, a)
        d.text((x0 + wd + 28, y), c["text"], font=f_t, fill=mix(BG, FG, a), stroke_width=4, stroke_fill=BG)


def draw_outro(d, t):
    k = smooth((t - (T_REVEAL + T_ZOOM * 0.75)) / 1.0)
    if k <= 0:
        return
    rows = [("claude", "Claude (2023.03)", "Claude Opus 5.5", "5 世代", 872),
            ("openai", "ChatGPT (2022.11)", "GPT-6 Astra", "5 系統", 922)]
    for key, before, after, gens, y in rows:
        ln = LANES[key]
        n = sum(1 for e in events if lines[e["line"]]["lane"] == key and e["kind"] != "end")
        yy = y + (1 - k) * 10
        f_b, f_a, f_s = F(22, 4), F(32, 8), F(18, 5)
        wtot = f_b.getlength(before) + 60 + f_a.getlength(after) + 24 + f_s.getlength(f"{gens} · {n} リリース")
        x = (W - wtot) / 2
        d.text((x, yy + 8), before, font=f_b, fill=mix(BG, MUTED, k))
        x += f_b.getlength(before) + 16
        d.text((x, yy + 4), "→", font=F(26, 6), fill=mix(BG, ln["color"], k))
        x += 44
        d.text((x, yy), after, font=f_a, fill=mix(BG, FG, k))
        x += f_a.getlength(after) + 24
        d.text((x, yy + 11), f"{gens} · {n} リリース", font=f_s, fill=mix(BG, ln["color"], k))
    src = ("出典: Anthropic / OpenAI の公式発表・リリースノート・モデル廃止情報（2026-10-01 時点）"
           "　提供終了日: Claude = API、OpenAI = ChatGPT")
    f = F(17, 4)
    d.text(((W - f.getlength(src)) / 2, 980), src, font=f, fill=mix(BG, (178, 183, 195), k))


def draw_intro(d, t):
    a = smooth(t / 0.8) * (1 - smooth((t - (T_INTRO - 0.7)) / 0.7))
    if a <= 0:
        return
    d.rectangle([0, 0, W, H], fill=BG)
    f1, f2 = F(92, 8), F(34, 4)
    t1 = "Claude × ChatGPT"
    t2 = "進化の軌跡  2022.11 → 2026.10"
    rise = (1 - smooth(t / 1.0)) * 30
    d.text(((W - f1.getlength(t1)) / 2, 420 + rise), t1, font=f1, fill=mix(BG, FG, a))
    d.text(((W - f2.getlength(t2)) / 2, 560 + rise), t2, font=f2, fill=mix(BG, MUTED, a))
    w = 360 * smooth((t - 0.3) / 1.0)
    d.line([(W / 2 - w, 530 + rise), (W / 2, 530 + rise)], fill=mix(BG, LANES["claude"]["color"], a), width=4)
    d.line([(W / 2, 530 + rise), (W / 2 + w, 530 + rise)], fill=mix(BG, LANES["openai"]["color"], a), width=4)


def render(t):
    set_camera(t)
    frame = Image.new("RGBA", (W, H), BG + (255,))
    d = ImageDraw.Draw(frame, "RGBA")
    p = playhead(t)
    z = smooth((t - T_REVEAL) / 1.0)
    draw_playhead(d, p, z)
    for lane in LANES:
        draw_lane(frame, lane, t, p, z)
    d = ImageDraw.Draw(frame, "RGBA")
    draw_pace(d, t, p)
    draw_axis(d, p)
    draw_edges(frame)
    d = ImageDraw.Draw(frame, "RGBA")
    draw_lane_titles(d)
    draw_header(d, p, z)
    draw_caption(frame, d, t)
    draw_legend(d, z)
    draw_outro(d, t)
    if t < T_INTRO:
        draw_intro(d, t)
    fade = smooth((t - (TOTAL - T_FADE)) / T_FADE)
    if fade > 0:
        frame.alpha_composite(Image.new("RGBA", (W, H), (0, 0, 0, int(255 * fade))))
    return frame.convert("RGB")


def main():
    args = sys.argv[1:]
    if args and args[0] == "--preview":
        preview_dir = os.path.join(OUT_DIR, "previews")
        os.makedirs(preview_dir, exist_ok=True)
        for s in args[1:]:
            render(float(s)).save(os.path.join(preview_dir, f"preview_{s}.png"))
        return
    out = args[0] if args else os.path.join(OUT_DIR, "claude_chatgpt_evolution.mp4")
    default_audio = os.path.join(OUT_DIR, "music.wav")
    audio = args[1] if len(args) > 1 else (default_audio if os.path.exists(default_audio) else None)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    n = int(TOTAL * FPS)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-"]
    if audio:
        cmd += ["-i", audio, "-c:a", "aac", "-b:a", "192k", "-shortest"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "medium",
            "-movflags", "+faststart", out]
    ff = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for i in range(n):
        ff.stdin.write(render(i / FPS).tobytes())
        if i % 150 == 0:
            print(f"{i}/{n}", file=sys.stderr, flush=True)
    ff.stdin.close()
    ff.wait()
    print(f"wrote {out} ({TOTAL:.1f}s)")


if __name__ == "__main__":
    main()
