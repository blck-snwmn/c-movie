"""Synthesize background music synced to the render.py video and write it as WAV.

Pad, bass and arpeggio play over an Am - F - C - G progression; drums join as the timeline
advances so the track builds up. Bells mark new generations, small chimes mark flagship models
and a falling tone marks retirements, all at the video's event times. At the final pull-back
(T_REVEAL) the drums stop and the last chord rings out.

usage: uv run python make_music.py [out.wav]   (default: out/music.wav)
"""
import os
import sys
import wave

import numpy as np

import render as R

SR = 44100
BPM = 96
BEAT = 60 / BPM
BAR = BEAT * 4
N = int(R.TOTAL * SR) + SR
t_all = np.arange(N) / SR

# (bass note, pad notes) as MIDI note numbers. Each chord lasts two bars.
PROG = [
    (45, [57, 60, 64, 71]),   # Am(add9)
    (41, [53, 57, 60, 64]),   # Fmaj7
    (48, [55, 60, 64, 67]),   # C
    (43, [55, 59, 62, 67]),   # G
]
CHORD_LEN = BAR * 2


def hz(n):
    return 440.0 * 2 ** ((n - 69) / 12)


def chord_at(t):
    return PROG[int(t // CHORD_LEN) % len(PROG)]


def smoothstep(x):
    x = np.clip(x, 0, 1)
    return x * x * (3 - 2 * x)


def seg(start, dur):
    i0 = max(0, int(start * SR))
    i1 = min(N, int((start + dur) * SR))
    return i0, i1, (np.arange(i1 - i0) / SR)


def add(buf, start, sig):
    i0 = int(start * SR)
    if i0 >= N:
        return
    sig = sig[: N - i0]
    buf[i0: i0 + len(sig)] += sig


def time_of(date):
    return R.time_at(R.month_of(date))


T_DRUMS = time_of("2023-10-01")      # kick starts
T_HATS = time_of("2024-10-01")       # hi-hats start
T_CLAP = time_of("2025-06-01")       # claps start
T_END_DRUMS = R.T_REVEAL
T_MUSIC_END = R.TOTAL


def intensity(t):
    """0 -> 1, rising from the end of the intro to the end of the main part."""
    return float(np.clip((t - R.T_INTRO) / (R.T_REVEAL - R.T_INTRO), 0, 1))


# ---------------------------------------------------------------- pad
pad = np.zeros(N)
n_chords = int(R.TOTAL / CHORD_LEN) + 2
for k in range(n_chords):
    start = k * CHORD_LEN
    _, notes = PROG[k % len(PROG)]
    dur = CHORD_LEN + 1.2
    i0, i1, tt = seg(start, dur)
    if i1 <= i0:
        continue
    env = smoothstep(tt / 1.0) * smoothstep((dur - tt) / 1.2)
    sig = np.zeros_like(tt)
    for n in notes:
        f = hz(n)
        for det in (-0.0018, 0.0018):
            for h, amp in ((1, 1.0), (2, 0.35), (3, 0.15), (4, 0.06)):
                sig += amp * np.sin(2 * np.pi * f * (1 + det) * h * tt + h * n)
    sig *= env * (0.85 + 0.15 * np.sin(2 * np.pi * 0.18 * (tt + start)))
    pad[i0:i1] += sig
pad *= 0.022

# ---------------------------------------------------------------- bass (eighth notes)
bass = np.zeros(N)
t = R.T_INTRO
while t < T_END_DRUMS + BAR * 2:
    root, _ = chord_at(t)
    f = hz(root)
    _, _, tt = seg(t, BEAT * 0.5)
    env = np.exp(-tt / 0.16) * smoothstep(tt / 0.005)
    sig = (np.sin(2 * np.pi * f * tt) + 0.35 * np.sin(4 * np.pi * f * tt)) * env
    lvl = 0.10 + 0.12 * intensity(t)
    if t > T_END_DRUMS:
        lvl *= max(0.0, 1 - (t - T_END_DRUMS) / (BAR * 2))
    add(bass, t, sig * lvl)
    t += BEAT / 2

# ---------------------------------------------------------------- arpeggio (sixteenths, panned L/R)
arp_l, arp_r = np.zeros(N), np.zeros(N)
PATTERN = [0, 1, 2, 3, 2, 1, 3, 2]
t = R.T_INTRO + BAR
step = 0
while t < R.TOTAL - 2.0:
    _, notes = chord_at(t)
    n = notes[PATTERN[step % len(PATTERN)]] + 12
    f = hz(n)
    _, _, tt = seg(t, 0.5)
    env = np.exp(-tt / 0.14) * smoothstep(tt / 0.003)
    sig = (np.sin(2 * np.pi * f * tt) + 0.25 * np.sin(4 * np.pi * f * tt) + 0.08 * np.sin(6 * np.pi * f * tt)) * env
    inten = intensity(t)
    lvl = 0.035 + 0.06 * inten
    if t > R.T_REVEAL:
        lvl *= 0.6
    # eighth notes early on, sixteenths once the track builds up
    if inten < 0.35 and step % 2 == 1:
        lvl = 0
    pan = 0.3 if step % 2 else -0.3
    add(arp_l, t, sig * lvl * (1 - pan))
    add(arp_r, t, sig * lvl * (1 + pan))
    t += BEAT / 4
    step += 1

# ---------------------------------------------------------------- drums
drums = np.zeros(N)
rng = np.random.default_rng(7)
t = T_DRUMS - ((T_DRUMS - R.T_INTRO) % BEAT)
beat_i = 0
while t < T_END_DRUMS:
    inten = intensity(t)
    # kick (every beat)
    _, _, tt = seg(t, 0.35)
    f = 45 + 80 * np.exp(-tt / 0.03)
    kick = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tt / 0.14)
    add(drums, t, kick * (0.18 + 0.14 * inten))
    # hi-hat (off-beats)
    if t >= T_HATS:
        th = t + BEAT / 2
        _, _, tt = seg(th, 0.06)
        noise = rng.standard_normal(len(tt))
        hat = np.diff(noise, prepend=0) * np.exp(-tt / 0.018)
        add(drums, th, hat * 0.028)
    # clap (beats 2 and 4)
    if t >= T_CLAP and beat_i % 2 == 1:
        _, _, tt = seg(t, 0.2)
        noise = rng.standard_normal(len(tt))
        clap = (noise - np.roll(noise, 3)) * np.exp(-tt / 0.06)
        add(drums, t, clap * 0.045)
    t += BEAT
    beat_i += 1

# ---------------------------------------------------------------- event sounds
fx = np.zeros(N)


def bell(t0, n, lvl, decay=1.8):
    f = hz(n)
    _, _, tt = seg(t0, decay * 2.2)
    sig = np.zeros_like(tt)
    for ratio, amp, dk in ((1, 1.0, 1.0), (2.0, 0.45, 0.6), (3.01, 0.25, 0.4), (4.2, 0.12, 0.25)):
        sig += amp * np.sin(2 * np.pi * f * ratio * tt) * np.exp(-tt / (decay * dk))
    sig *= smoothstep(tt / 0.004)
    add(fx, t0, sig * lvl)


for e in R.events:
    tc = e["tc"]
    _, notes = chord_at(tc)
    if e["kind"] == "gen":
        # bells stacked on chord tones
        bell(tc, notes[0] + 24, 0.09, 2.2)
        bell(tc + 0.06, notes[2] + 24, 0.06, 2.0)
        bell(tc + 0.12, notes[3] + 24, 0.045, 1.8)
    elif e["kind"] == "major":
        bell(tc, notes[2] + 24, 0.04, 0.9)
    elif e["kind"] == "end":
        # soft falling tone
        _, _, tt = seg(tc, 1.4)
        f = hz(notes[0]) * np.exp(-tt * 0.9)
        sig = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tt / 0.5) * smoothstep(tt / 0.05)
        add(fx, tc, sig * 0.05)

# final pull-back: reverse-cymbal style swell, then ring the last chord
_, _, tt = seg(R.T_REVEAL - 1.6, 1.6)
noise = rng.standard_normal(len(tt))
swell = np.diff(noise, prepend=0) * (tt / 1.6) ** 3
add(fx, R.T_REVEAL - 1.6, swell * 0.05)
for i, n in enumerate([57, 64, 69, 71, 76]):
    bell(R.T_REVEAL + i * 0.05, n + 12, 0.05, 3.0)

# ---------------------------------------------------------------- mix
def echo(x, delay, fb, taps=5):
    out = x.copy()
    d = int(delay * SR)
    g = fb
    for k in range(1, taps + 1):
        out[d * k:] += x[: N - d * k] * g
        g *= fb
    return out


fx_wet = echo(fx, BEAT * 0.75, 0.38)
arp_l = echo(arp_l, BEAT * 0.75, 0.3)
arp_r = echo(arp_r, BEAT * 0.5, 0.3)

left = pad + bass + drums + arp_l + fx_wet * 0.9 + echo(fx, BEAT * 0.5, 0.3) * 0.2
right = pad + bass + drums + arp_r + fx_wet * 0.7 + fx * 0.3

master = np.stack([left, right], axis=1)
fade_in = smoothstep(t_all / 1.5)
fade_out = smoothstep((R.TOTAL - t_all) / 3.0)
master *= (fade_in * fade_out)[:, None]
master = np.tanh(master * 1.6) / np.tanh(1.6)
master /= np.max(np.abs(master)) / 0.89
master = master[: int(R.TOTAL * SR)]

out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(R.OUT_DIR, "music.wav")
os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
with wave.open(out, "wb") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes((master * 32767).astype("<i2").tobytes())
print(f"wrote {out} ({R.TOTAL:.1f}s)")
