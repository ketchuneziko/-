#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rap rebuild from the original vocal take.
Dark boom-bap / trap hybrid, 88 BPM, A minor.
Outputs: master, instrumental, acapella, separated stems.
"""
import os, math, json, subprocess, tempfile, shutil, zipfile
import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfilt, fftconvolve, resample_poly
import imageio_ffmpeg
try:
    import parselmouth as pm
except Exception:
    pm = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "Натуральное звучание C Мажор.m4a")
OUT = os.path.join(ROOT, "song")
WORK = os.path.join(ROOT, "work")
SAMPLES = os.path.join(OUT, "samples", "SR16")
os.makedirs(OUT, exist_ok=True); os.makedirs(WORK, exist_ok=True)
FF = imageio_ffmpeg.get_ffmpeg_exe()
SR = 44100
BPM = 88.0
BEAT = 60.0 / BPM
BAR = 4.0 * BEAT
BARS = 40
TAIL = 3.0
N = int((BARS * BAR + TAIL) * SR)
rng = np.random.default_rng(88088)

def run(cmd):
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if r.returncode:
        raise RuntimeError(r.stderr.decode("utf-8", "ignore")[-6000:])
    return r.stdout.decode("utf-8", "ignore") + r.stderr.decode("utf-8", "ignore")

def ff(args):
    return run([FF, "-hide_banner", "-y"] + args)

def read_wav(p):
    x, sr = sf.read(p, dtype="float32", always_2d=True)
    if sr != SR:
        x = resample_poly(x, SR, sr).astype(np.float32)
    return x

def mono(x):
    return x.mean(axis=1) if x.ndim == 2 else x

def write_wav(p, x, subtype="FLOAT"):
    sf.write(p, x, SR, subtype=subtype)

def filt(x, cutoff, btype="lowpass", order=2):
    sos = butter(order, cutoff, btype=btype, fs=SR, output="sos")
    if x.ndim == 1:
        return sosfilt(sos, x).astype(np.float32)
    return np.stack([sosfilt(sos, x[:, c]) for c in range(x.shape[1])], axis=1).astype(np.float32)

def peak_norm(x, target=0.9):
    return (x * (target / (np.max(np.abs(x)) + 1e-9))).astype(np.float32)

def rms(x):
    return float(np.sqrt(np.mean(np.asarray(x, dtype=np.float64) ** 2) + 1e-12))

def fade(x, fi=0.003, fo=0.03):
    x = x.copy(); n = len(x)
    a = min(int(fi * SR), n); b = min(int(fo * SR), n)
    if a: x[:a] *= np.linspace(0, 1, a, dtype=np.float32)
    if b: x[-b:] *= np.linspace(1, 0, b, dtype=np.float32)
    return x

def trim_silence(x, thr=0.003):
    a = np.argmax(np.abs(x) > thr)
    rev = np.argmax(np.abs(x[::-1]) > thr)
    b = len(x) - rev
    if b <= a: return x
    return x[max(0, a - 120):min(len(x), b + 400)]

def layer(*signals):
    n = max(len(s) for s in signals)
    out = np.zeros(n, np.float32)
    for s in signals:
        out[:len(s)] += s
    return out

def add(bus, sig, t, gain=1.0, pan=0.0):
    i = int(round(t * SR))
    if i >= N or i < 0: return
    if sig.ndim == 1:
        L = math.cos((pan + 1) * math.pi / 4); R = math.sin((pan + 1) * math.pi / 4)
        sig = np.stack([sig * L, sig * R], axis=1)
    n = min(len(sig), N - i)
    if n > 0: bus[i:i+n] += sig[:n] * gain

def stretch_pitch(x, tempo=1.0, pitch=1.0):
    if abs(tempo - 1) < 1e-3 and abs(pitch - 1) < 1e-3:
        return x.copy()
    with tempfile.TemporaryDirectory(dir=WORK) as td:
        a = os.path.join(td, "a.wav"); b = os.path.join(td, "b.wav")
        write_wav(a, x)
        rb = (f"rubberband=tempo={tempo:.6f}:pitch={pitch:.6f}"
              ":transients=mixed:detector=compound:phase=laminar:window=standard"
              ":smoothing=on:formant=preserved:pitchq=quality:channels=together")
        ff(["-i", a, "-af", rb, "-ar", str(SR), "-ac", "1", b])
        return mono(read_wav(b)).astype(np.float32)

def note_freq(m): return 440.0 * 2 ** ((m - 69) / 12.0)

def make_ir(seconds, decay, lp, hp):
    n = int(seconds * SR); t = np.arange(n) / SR
    ir = np.zeros((n, 2), np.float32)
    for c in range(2):
        noise = rng.standard_normal(n).astype(np.float32)
        tail = noise * np.exp(-decay * t / seconds).astype(np.float32)
        tail = filt(tail, lp, "lowpass", 2); tail = filt(tail, hp, "highpass", 2)
        early = np.zeros(n, np.float32)
        for dt, g in [(0.009, .5), (0.017, .38), (0.029, .30), (0.041, .24), (0.057, .18)]:
            j = int(dt * SR) + c * 29
            if j < n: early[j] += g
        ir[:, c] = tail * 0.75 + early
    ir /= (np.sqrt(np.sum(ir.astype(np.float64) ** 2)) + 1e-9)
    return ir.astype(np.float32)

IR_ROOM = make_ir(0.45, 7.5, 4500, 400)
IR_PLATE = make_ir(1.05, 6.2, 5200, 300)
IR_DARK = make_ir(1.8, 5.0, 2600, 200)

def reverb_send(x, ir, wet=0.2):
    if x.ndim == 1: x = np.stack([x, x], axis=1)
    y = np.zeros_like(x)
    for c in range(2):
        y[:, c] = fftconvolve(x[:, c], ir[:, c], mode="full")[:len(x)]
    return (x + wet * y).astype(np.float32)

def delay_send(x, delay, feedback=0.32, taps=4, lp=3200, wet=0.2):
    if x.ndim == 1: x = np.stack([x, x], axis=1)
    y = np.zeros_like(x); d = int(delay * SR)
    for k in range(1, taps + 1):
        i = k * d
        if i >= len(x): break
        tap = filt(x, lp, "lowpass", 2) * (feedback ** k) * wet
        if k % 2: tap = tap[:, ::-1]
        y[i:] += tap[:-i]
    return y.astype(np.float32)

def section_mask(bars):
    m = np.zeros(N, np.float32)
    for b in bars:
        a = int(b * BAR * SR); z = min(int((b + 1) * BAR * SR), N)
        m[a:z] = 1
    return m

# ---------------- source vocal ----------------
raw_path = os.path.join(WORK, "source.wav")
if not os.path.exists(raw_path):
    ff(["-i", SRC, "-ac", "1", "-ar", str(SR), raw_path])
raw = mono(read_wav(raw_path))

PHRASES = [
    (1.39,4.25),(5.26,8.57),(9.07,11.24),(11.79,14.05),(14.39,16.57),(17.12,19.57),
    (20.04,22.50),(23.39,25.79),(26.31,28.67),(29.11,31.95),(32.69,34.07),(34.57,36.91),
    (37.43,39.52),(39.95,42.25),(42.69,45.79),(46.29,48.74),(49.05,51.18),(51.54,54.30),
    (54.67,57.01),(57.38,59.67),(60.01,62.59),(62.99,65.29),(65.63,67.74),(68.75,71.69),
    (71.99,74.14),(74.52,76.78),(77.09,79.30),(79.85,82.37),(82.86,85.26),(85.86,88.19),
    (88.47,91.01),(91.38,93.95),(94.37,96.88),
]
PHRASE_BAR = {}
for i in range(8): PHRASE_BAR[i] = 2 + i       # verse 1
for i in range(8): PHRASE_BAR[8+i] = 10 + i    # hook 1
for i in range(8): PHRASE_BAR[16+i] = 18 + i   # verse 2
for i in range(4): PHRASE_BAR[24+i] = 26 + i   # bridge
for i in range(5): PHRASE_BAR[28+i] = 32 + i   # final hook

pitch_path = os.path.join(WORK, "pitch.npz")
if not os.path.exists(pitch_path) and pm is not None:
    snd = pm.Sound(raw.astype(np.float64), SR)
    pit = snd.to_pitch_ac(time_step=0.01, pitch_floor=65, pitch_ceiling=600,
                          silence_threshold=0.03, voicing_threshold=0.45)
    np.savez(pitch_path, t=pit.xs(), f=pit.selected_array["frequency"])
pitch_data = np.load(pitch_path) if os.path.exists(pitch_path) else None

def phrase_cents(a, b):
    if pitch_data is None: return 0.0
    t = pitch_data["t"]; f = pitch_data["f"]
    sel = f[(t >= a) & (t <= b) & (f > 0)]
    if len(sel) < 5: return 0.0
    m = 69 + 12 * np.log2(sel / 440.0)
    return float(np.clip(np.median((m - np.round(m)) * 100.0), -14, 14))

vocal_dry = np.zeros((N, 2), np.float32)
vocal_dbl = np.zeros((N, 2), np.float32)
vocal_adlib = np.zeros((N, 2), np.float32)
phrase_audio = []
hook_bars = list(range(10, 18)) + list(range(32, 38))
for idx, (a, b) in enumerate(PHRASES):
    bar = PHRASE_BAR[idx]
    ia = max(0, int((a - 0.045) * SR)); iz = min(len(raw), int((b + 0.09) * SR))
    seg = fade(raw[ia:iz].copy(), 0.006, 0.04)
    d = (iz - ia) / SR
    max_len = BAR * 0.965
    target = min(d, max_len)
    if d / target > 1.28: target = d / 1.28
    tempo = d / target if target < d else 1.0
    cents = phrase_cents(a, b)
    pitch = 2 ** (-cents / 1200.0) if abs(cents) > 4 else 1.0
    y = stretch_pitch(seg, tempo=tempo, pitch=pitch)
    want = int(target * SR)
    if len(y) < want: y = np.pad(y, (0, want - len(y)))
    y = fade(y[:want], 0.006, 0.05)
    active = y[np.abs(y) > 0.018]
    r = rms(active) if len(active) else rms(y)
    y *= float(np.clip(0.17 / (r + 1e-9), 0.5, 2.6))
    phrase_audio.append(y)
    t = bar * BAR + 0.025
    add(vocal_dry, y, t, 1.0, 0.0)
    if bar in hook_bars:
        dl = stretch_pitch(y, tempo=1.0, pitch=2 ** (-6 / 1200))
        dr = stretch_pitch(y, tempo=1.0, pitch=2 ** (6 / 1200))
        add(vocal_dbl, fade(dl, .01, .06), t + 0.014, 0.20, -0.7)
        add(vocal_dbl, fade(dr, .01, .06), t + 0.023, 0.18, 0.7)
        # short adlib tail from the end of the phrase
        tail = y[-int(0.42 * SR):]
        if len(tail) > int(0.15 * SR):
            ad = stretch_pitch(tail, tempo=1.0, pitch=2 ** (12 / 12))
            add(vocal_adlib, fade(ad, .01, .12), t + target + 0.10 * BEAT, 0.16, 0.35)

# vocal chain
vp = os.path.join(WORK, "vocal_pre.wav"); vo = os.path.join(WORK, "vocal_chain.wav")
write_wav(vp, vocal_dry)
chain = (
    "highpass=f=75:p=2,"
    "lowpass=f=17000:p=2,"
    "equalizer=f=250:t=q:w=1.0:g=-2.4,"
    "equalizer=f=1200:t=q:w=1.1:g=0.8,"
    "equalizer=f=3200:t=q:w=0.9:g=2.2,"
    "treble=f=10500:g=1.6,"
    "deesser=i=0.25:m=0.4:f=0.6,"
    "acompressor=threshold=0.10:ratio=3.0:attack=6:release=120:makeup=1.5:knee=2.2:detection=rms,"
    "alimiter=limit=0.89:attack=5:release=90:level=false:latency=true"
)
ff(["-i", vp, "-af", chain, "-ar", str(SR), "-ac", "2", vo])
vocal_chain = read_wav(vo)
if len(vocal_chain) < N: vocal_chain = np.pad(vocal_chain, ((0, N - len(vocal_chain)), (0, 0)))
vocal_chain = vocal_chain[:N]
hook_mask = section_mask(hook_bars)[:, None]
vocal_dbl = filt(vocal_dbl, 5600, "lowpass", 2)
vocal_adlib = reverb_send(vocal_adlib, IR_PLATE, 0.35) + delay_send(vocal_adlib, 0.75 * BEAT, .38, 4, 2800, .35)
vocal_bus = vocal_chain + vocal_dbl * hook_mask + vocal_adlib
v_verb = np.zeros_like(vocal_chain)
send = vocal_chain * (0.10 + 0.07 * hook_mask)
for c in range(2):
    v_verb[:, c] = fftconvolve(send[:, c], IR_ROOM[:, c], mode="full")[:N]
v_dly = delay_send(vocal_chain * (0.07 + 0.07 * hook_mask), 0.75 * BEAT, .30, 4, 3000, 1.0)
vocal_bus += v_verb * 0.9 + v_dly * 0.75

# ---------------- drum samples / synthesis ----------------
def load_sample(name):
    x = mono(read_wav(os.path.join(SAMPLES, name)))
    return trim_silence(x)

s_kick = load_sample("Kick.wav")[:int(0.32 * SR)]
s_snare = load_sample("Snare.wav")[:int(0.26 * SR)]
s_clap = load_sample("Claps.wav")[:int(0.18 * SR)]
s_hat = load_sample("ClosedHat.wav")[:int(0.07 * SR)]
s_ohat = load_sample("OpenHat.wav")[:int(0.28 * SR)]

def synth_kick():
    n = int(0.42 * SR); t = np.arange(n) / SR
    f = 42 + 95 * np.exp(-t / 0.022)
    ph = 2 * np.pi * np.cumsum(f) / SR
    body = np.sin(ph) * np.exp(-t / 0.13)
    click = filt(rng.standard_normal(n).astype(np.float32), 2200, "highpass", 2) * np.exp(-t / 0.004) * 0.35
    x = np.tanh(1.7 * (body + click)) * np.minimum(t / 0.001, 1)
    return peak_norm(fade(x, .001, .04), .95)

def synth_subkick():
    n = int(0.30 * SR); t = np.arange(n) / SR
    f = 52 + 30 * np.exp(-t / 0.03)
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.11)
    return peak_norm(fade(x, .002, .04), .8)

def synth_snare_noise():
    n = int(0.24 * SR); t = np.arange(n) / SR
    x = filt(rng.standard_normal(n).astype(np.float32), [1400, 8000], "bandpass", 2) * np.exp(-t / 0.07)
    x += np.sin(2 * np.pi * 190 * t) * np.exp(-t / 0.045) * 0.4
    return peak_norm(fade(x, .001, .04), .8)

def synth_hat():
    n = int(0.07 * SR); t = np.arange(n) / SR
    noise = filt(rng.standard_normal(n).astype(np.float32), 7500, "highpass", 3)
    metal = sum(np.sign(np.sin(2 * np.pi * f * t)) for f in [4300, 5600, 6700, 8200]) * 0.10
    return peak_norm(fade((noise * .8 + metal) * np.exp(-t / 0.018), .0005, .02), .5)

KICK = peak_norm(layer(fade(s_kick, .001, .03) * 0.7, synth_kick() * 0.6, synth_subkick() * 0.5), .95)
SNARE = peak_norm(layer(fade(s_snare, .001, .03) * 0.75, synth_snare_noise() * 0.55, fade(s_clap, .001, .03) * 0.35), .9)
CLAP = peak_norm(layer(fade(s_clap, .001, .03) * 0.9, synth_snare_noise() * 0.2), .75)
HAT = peak_norm(layer(fade(s_hat, .0005, .02) * 0.6, synth_hat() * 0.6), .55)
OHAT = peak_norm(fade(s_ohat, .001, .05) * 0.8, .55)
GHOST = peak_norm(filt(SNARE, [900, 5000], "bandpass", 2), .35)

def shaker():
    n = int(0.10 * SR); t = np.arange(n) / SR
    x = filt(rng.standard_normal(n).astype(np.float32), 5200, "highpass", 2) * np.exp(-t / 0.035) * np.minimum(t / 0.003, 1)
    return peak_norm(fade(x, .001, .02), .32)
SHAKER = shaker()

def rim():
    n = int(0.06 * SR); t = np.arange(n) / SR
    x = (np.sin(2 * np.pi * 840 * t) * .5 + filt(rng.standard_normal(n).astype(np.float32), [1600, 5200], "bandpass", 2) * .5) * np.exp(-t / 0.011)
    return peak_norm(fade(x, .0005, .015), .45)
RIM = rim()

drums = np.zeros((N, 2), np.float32)
bass_bus = np.zeros((N, 2), np.float32)
music_bus = np.zeros((N, 2), np.float32)
fx_bus = np.zeros((N, 2), np.float32)

# ---------------- 808 / harmony ----------------
PROG = ["Am", "F", "G", "Em"]
ROOTS = {"Am": 33, "F": 29, "G": 31, "Em": 28}
CHORDS = {
    "Am": [57, 60, 64, 71],
    "F":  [53, 57, 60, 64],
    "G":  [55, 59, 62, 67],
    "Em": [52, 55, 59, 62],
}
def chord_of(bar): return PROG[bar % 4]

def bass808(m, dur=1.2, vel=.8, glide_to=None):
    n = int((dur + 0.18) * SR); t = np.arange(n) / SR
    f0 = note_freq(m); f1 = note_freq(glide_to) if glide_to else f0
    f = f0 + (f1 - f0) * np.clip((t - dur * 0.62) / max(dur * 0.38, 1e-3), 0, 1)
    f *= (1 + 0.75 * np.exp(-t / 0.03))
    ph = 2 * np.pi * np.cumsum(f) / SR
    x = np.sin(ph) + 0.24 * np.sin(2 * ph) + 0.09 * np.sin(3 * ph)
    x = np.tanh(1.8 * x)
    env = np.minimum(t / 0.004, 1) * np.clip((dur + 0.12 - t) / 0.12, 0, 1) * (0.85 + 0.15 * np.exp(-t / 0.4))
    return fade((x * env * vel * 0.72).astype(np.float32), .003, .08)

def dark_piano(m, dur=1.6, vel=.6):
    n = int((dur + 0.4) * SR); t = np.arange(n) / SR
    f = note_freq(m)
    x = np.zeros(n, np.float32)
    for h, a in [(1, 1), (2, .42), (3, .20), (4, .10), (5, .05)]:
        x += a * np.sin(2 * np.pi * f * h * t + 0.12 * h) * np.exp(-t * (1.1 + 0.35 * h))
    x += filt(rng.standard_normal(n).astype(np.float32), 2500, "lowpass", 2) * np.exp(-t / 0.012) * 0.04
    env = np.minimum(t / 0.004, 1) * np.clip((dur + 0.35 - t) / 0.35, 0, 1)
    x = filt(x * env, 3000, "lowpass", 2)
    return (x * vel * 0.5).astype(np.float32)

def bell(m, dur=.5, vel=.5):
    n = int((dur + .3) * SR); t = np.arange(n) / SR
    f = note_freq(m)
    mod = np.sin(2 * np.pi * f * 2.76 * t) * (1.6 * np.exp(-t / .18))
    x = np.sin(2 * np.pi * f * t + mod) * np.exp(-t / .28)
    x += np.sin(2 * np.pi * f * 2.01 * t) * np.exp(-t / .12) * .2
    env = np.minimum(t / .003, 1) * np.clip((dur + .25 - t) / .25, 0, 1)
    return (x * env * vel * .42).astype(np.float32)

def pad(m, dur, vel=.35):
    n = int((dur + 1) * SR); t = np.arange(n) / SR
    f = note_freq(m)
    x = np.zeros(n, np.float32)
    for det, g in [(-.005, .5), (0, .6), (.005, .5)]:
        saw = 2 * ((t * f * (1 + det)) % 1) - 1
        x += saw * g
    x = filt(x, 780, "lowpass", 3)
    env = np.minimum(t / .6, 1) * np.clip((dur + .9 - t) / .9, 0, 1)
    return (x * env * vel * .20).astype(np.float32)

# ---------------- patterns ----------------
SWING = 0.058 * BEAT

def drum_pattern(bar, intensity):
    t0 = bar * BAR
    if intensity <= 0: return
    if intensity < 1:
        add(drums, HAT, t0 + 0.0, .18, .2)
        add(drums, HAT, t0 + 2 * BEAT, .14, -.2)
        add(drums, RIM, t0 + 3 * BEAT, .18, .1)
        return
    if intensity >= 3:
        kicks = [0, .5, 1.5, 2, 2.5, 3.5]
        snares = [1, 3]
        hat_steps = 16
    elif intensity >= 2:
        kicks = [0, .75, 1.75, 2.5]
        snares = [1, 3]
        hat_steps = 8
    else:
        kicks = [0, .75, 2.25]
        snares = [1, 3]
        hat_steps = 8
    for k in kicks:
        add(drums, KICK, t0 + k * BEAT, .92 if k == 0 else .74, 0)
    for s in snares:
        add(drums, SNARE, t0 + s * BEAT, .78, .02)
        if intensity >= 2: add(drums, CLAP, t0 + s * BEAT + .006, .34, -.04)
    add(drums, GHOST, t0 + 2.75 * BEAT, .14 if intensity >= 2 else .10, -.25)
    for i in range(hat_steps):
        step = i * (4.0 / hat_steps)
        tt = t0 + step * BEAT + (SWING if i % 2 else 0)
        g = .30 if i % (hat_steps // 4) == 0 else .20
        if intensity >= 3 and i % 2: g *= .8
        add(drums, HAT, tt, g, -.28 if i % 2 else .28)
    if intensity >= 2:
        add(drums, OHAT, t0 + 3.5 * BEAT + SWING, .24, .35)
        for i in range(4):
            add(drums, SHAKER, t0 + (i + .5) * BEAT + SWING * .5, .13, -.4 if i % 2 else .4)
    if intensity >= 3:
        for i in range(6):
            add(drums, HAT, t0 + (2.5 + i / 6.0) * BEAT, .15, -.4 + i * .16)
        add(drums, RIM, t0 + 1.75 * BEAT, .18, -.35)
        if bar % 4 == 3:
            for i in range(8):
                add(drums, SNARE, t0 + (3.0 + i / 8.0) * BEAT, .10 + i * .015, -.3 + i * .08)

def bass_pattern(bar, intensity):
    if intensity <= 0: return
    t0 = bar * BAR; r = ROOTS[chord_of(bar)]
    if intensity >= 3:
        add(bass_bus, bass808(r, 1.25, .85), t0, pan=0)
        add(bass_bus, bass808(r, .5, .62, glide_to=r + 12), t0 + 1.5 * BEAT, pan=0)
        nxt = ROOTS[chord_of(bar + 1)]
        add(bass_bus, bass808(r, .95, .75, glide_to=nxt), t0 + 2.5 * BEAT, pan=0)
    elif intensity >= 2:
        add(bass_bus, bass808(r, 1.5, .72), t0, pan=0)
        add(bass_bus, bass808(r, .75, .58, glide_to=r + 7), t0 + 2.5 * BEAT, pan=0)
    elif intensity >= 1:
        add(bass_bus, bass808(r, 1.8, .62), t0, pan=0)
        add(bass_bus, bass808(r, .6, .45), t0 + 2.75 * BEAT, pan=0)
    else:
        add(bass_bus, bass808(r, 2.4, .42), t0, pan=0)

def music_pattern(bar, intensity):
    t0 = bar * BAR; ch = chord_of(bar); notes = CHORDS[ch]
    if intensity <= 0:
        add(music_bus, pad(notes[0] - 12, BAR, .22), t0, .5, 0)
        return
    g = .55 if intensity >= 3 else (.45 if intensity >= 2 else .36)
    for j, m in enumerate(notes):
        add(music_bus, dark_piano(m, BAR * .8, .5), t0 + .012 * j, g, -.3 + .2 * j)
    if intensity >= 2:
        for j, m in enumerate(notes[1:]):
            add(music_bus, dark_piano(m, .45, .42), t0 + 2.5 * BEAT + .01 * j, g * .6, -.2 + .2 * j)
    if intensity >= 1:
        add(music_bus, pad(notes[0] - 12, BAR * .95, .3), t0, .45, -.1)
        add(music_bus, pad(notes[2] - 12, BAR * .95, .25), t0, .45, .1)
    motif = [69, 72, 76, 74, 72, 69, 67, 69]
    if intensity >= 2 and bar % 2 == 1:
        for i, m in enumerate(motif[:4]):
            add(music_bus, bell(m, .32, .42), t0 + (2.5 + i * .375) * BEAT, .30, .2)
    if intensity >= 3 and bar % 4 == 3:
        for i, m in enumerate(motif[4:]):
            add(music_bus, bell(m, .3, .36), t0 + (1.0 + i * .5) * BEAT, .24, -.2)

# ---------------- FX / samples from voice ----------------
def riser(dur):
    n = int(dur * SR); t = np.arange(n) / SR; p = t / dur
    x = filt(rng.standard_normal(n).astype(np.float32), [700, 9000], "bandpass", 2)
    sweep = np.sin(2 * np.pi * (180 * t + 800 * t * t / dur))
    return fade((x * .5 + sweep * .22) * p ** 2.2, .05, .03).astype(np.float32)

def impact():
    n = int(1.5 * SR); t = np.arange(n) / SR
    low = np.sin(2 * np.pi * (36 * t + 26 * t * np.exp(-t / .2))) * np.exp(-t / .45)
    nz = filt(rng.standard_normal(n).astype(np.float32), 2800, "highpass", 2) * np.exp(-t / .35) * .4
    return peak_norm(fade(low + nz, .002, .2), .7)

def downlifter():
    n = int(1.3 * SR); t = np.arange(n) / SR; p = t / (n / SR)
    x = filt(rng.standard_normal(n).astype(np.float32), [500, 6000], "bandpass", 2)
    return fade(x * (1 - p) ** 2 * .5, .01, .1).astype(np.float32)

def crash():
    n = int(1.5 * SR); t = np.arange(n) / SR
    x = filt(rng.standard_normal(n).astype(np.float32), 4200, "highpass", 2) * np.exp(-t / .55)
    return peak_norm(fade(x, .002, .2), .45)

def make_chop(src, target_m, dur=.3):
    a = int(.10 * SR); b = min(len(src), a + int(.28 * SR))
    seg = src[a:b]
    if len(seg) < int(.12 * SR): seg = src[:int(.28 * SR)]
    src_m = 45.0
    if pm is not None:
        try:
            s = pm.Sound(seg.astype(np.float64), SR)
            p = s.to_pitch_ac(time_step=.01, pitch_floor=60, pitch_ceiling=500, silence_threshold=.03, voicing_threshold=.35)
            f = p.selected_array["frequency"]; f = f[f > 0]
            if len(f): src_m = float(np.median(69 + 12 * np.log2(f / 440)))
        except Exception: pass
    y = stretch_pitch(seg, pitch=2 ** ((target_m - src_m) / 12))
    want = int(dur * SR)
    return fade(np.pad(y[:want], (0, max(0, want - len(y)))), .008, .10)

CHOPS = [make_chop(phrase_audio[i], m, .32) for i, m in [(1, 57), (12, 60), (18, 64), (5, 62)]]
def chop_motif(t0, gain=.35):
    for i, k in enumerate([0, 1, 2, 3, 2, 1]):
        add(fx_bus, CHOPS[k], t0 + i * .5 * BEAT, gain * (.9 if i % 2 else 1), -.35 if i % 2 else .35)

def scratch(src, dur=.6):
    seg = src[int(.1 * SR):int(.4 * SR)]
    if len(seg) < 100: seg = src[:min(len(src), int(.3 * SR))]
    n = int(dur * SR); t = np.arange(n) / SR
    pos = (len(seg) - 1) * (0.5 + 0.48 * np.sin(2 * np.pi * 3.2 * t))
    idx = np.clip(pos.astype(int), 0, len(seg) - 1)
    x = seg[idx]
    x = filt(x, [500, 4500], "bandpass", 2)
    return fade(x, .01, .05).astype(np.float32)

# vinyl / air texture
t = np.arange(N) / SR
noise = rng.standard_normal(N).astype(np.float32)
air = filt(noise, [350, 3800], "bandpass", 2) * 0.012
crackle = np.zeros(N, np.float32)
for _ in range(int(N / SR * 8)):
    j = rng.integers(0, N - 200)
    crackle[j:j + 180] += (rng.standard_normal(180) * np.exp(-np.arange(180) / 32) * 0.05).astype(np.float32)
texture = np.stack([air + crackle * .7, np.roll(air, 137) + np.roll(crackle, 271) * .7], axis=1)
texture *= np.minimum(t / 2, 1).astype(np.float32)[:, None]
texture *= np.clip((N / SR - t) / 3, 0, 1).astype(np.float32)[:, None]
fx_bus += texture * 0.7

# ---------------- arrangement ----------------
for bar in range(BARS):
    if bar < 2: intensity = .5
    elif bar < 10: intensity = 1
    elif bar < 18: intensity = 3
    elif bar < 26: intensity = 1.5
    elif bar < 30: intensity = .7
    elif bar == 30: intensity = .3
    elif bar == 31: intensity = 0
    elif bar < 38: intensity = 3
    else: intensity = .5
    drum_pattern(bar, intensity)
    bass_pattern(bar, intensity)
    music_pattern(bar, intensity)

add(fx_bus, crash(), 10 * BAR, .30, -.1)
add(fx_bus, impact(), 10 * BAR, .5, 0)
add(fx_bus, riser(2 * BAR), 8 * BAR, .30, 0)
add(fx_bus, crash(), 32 * BAR, .35, .1)
add(fx_bus, impact(), 32 * BAR, .55, 0)
add(fx_bus, riser(.75 * BAR), 31 * BAR + .25 * BAR, .38, 0)
add(fx_bus, downlifter(), 30 * BAR, .4, 0)
add(fx_bus, crash(), 2 * BAR, .16, .2)
add(fx_bus, crash(), 38 * BAR, .20, -.2)
chop_motif(.25 * BAR, .30)
chop_motif(30 * BAR + .15 * BAR, .38)
chop_motif(37 * BAR, .32)
add(fx_bus, scratch(phrase_audio[1]), 30 * BAR + .5 * BAR, .28, -.2)
add(fx_bus, scratch(phrase_audio[12]), 30 * BAR + 1.25 * BAR, .24, .2)
# echo into pause
add(fx_bus, fade(phrase_audio[27][:int(.5 * SR)], .01, .2), 31 * BAR - .35 * BEAT, .22, .2)

# pause: near silence before final drop
pa = int(31 * BAR * SR); pb = int(32 * BAR * SR)
for bus in (drums, bass_bus, music_bus, vocal_bus):
    bus[pa:pb] *= 0.04
fx_bus[pa:pb] *= 0.55

# sidechain duck bass/music to kick
sc = np.zeros(N, np.float32)
for bar in range(BARS):
    if bar < 2 or bar >= 38 or bar == 31: continue
    t0 = bar * BAR
    kicks = [0, .5, 1.5, 2, 2.5, 3.5] if (10 <= bar < 18 or 32 <= bar < 38) else [0, .75, 2.25]
    for k in kicks:
        i = int((t0 + k * BEAT) * SR); nn = min(int(.20 * SR), N - i)
        if nn > 0: sc[i:i + nn] = np.maximum(sc[i:i + nn], np.exp(-np.arange(nn) / (.065 * SR)).astype(np.float32))
bass_bus *= (1 - .30 * sc)[:, None]
music_bus *= (1 - .16 * sc)[:, None]

# space
music_bus = reverb_send(music_bus, IR_DARK, .28) + delay_send(music_bus, .375 * BEAT, .26, 3, 2400, .18)
drums = reverb_send(drums, IR_ROOM, .08)
fx_bus = reverb_send(fx_bus, IR_DARK, .25)

# ---------------- mix / master ----------------
# vocal-forward rap balance
vocal_gain = 1.32 + 0.18 * hook_mask
vocal_stem = vocal_bus * vocal_gain
mix = (
    vocal_stem +
    drums * 0.85 +
    bass_bus * 0.60 +
    music_bus * 0.46 +
    fx_bus * 0.48
)
tt = np.arange(N) / SR
fade_env = np.minimum(tt / .12, 1) * np.clip(((N / SR) - tt) / 2.5, 0, 1)
mix *= fade_env.astype(np.float32)[:, None]
mix = np.tanh(mix * 1.12) / 1.12
premaster = os.path.join(WORK, "rap_premaster.wav"); write_wav(premaster, mix)

stats = ff(["-i", premaster, "-af", "loudnorm=I=-12:TP=-1.2:LRA=8:print_format=json", "-f", "null", "-"])
m = json.loads(stats[stats.rfind("{"):stats.rfind("}") + 1])
ln = (f"loudnorm=I=-12:TP=-1.2:LRA=8:measured_I={m['input_i']}:measured_TP={m['input_tp']}"
      f":measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true:print_format=summary")
master_wav = os.path.join(OUT, "rap_master.wav")
master_mp3 = os.path.join(OUT, "rap_master.mp3")
ff(["-i", premaster, "-af", ln + ",alimiter=limit=0.841:attack=5:release=80:level=false:latency=true",
    "-ar", str(SR), "-c:a", "pcm_s24le", master_wav])
ff(["-i", master_wav, "-codec:a", "libmp3lame", "-b:a", "320k",
    "-metadata", "title=Rap Rebuild", "-metadata", "artist=Original vocal + rap arrangement", master_mp3])

inst = drums * .85 + bass_bus * .60 + music_bus * .46 + fx_bus * .48
inst *= fade_env.astype(np.float32)[:, None]
inst = np.tanh(inst * 1.12) / 1.12
ip = os.path.join(WORK, "rap_inst.wav"); write_wav(ip, inst)
ff(["-i", ip, "-af", "loudnorm=I=-12:TP=-1.2:LRA=8:print_format=summary", "-codec:a", "libmp3lame", "-b:a", "320k", os.path.join(OUT, "rap_instrumental.mp3")])
ap = os.path.join(WORK, "rap_acapella.wav"); write_wav(ap, vocal_stem * fade_env.astype(np.float32)[:, None])
ff(["-i", ap, "-af", "loudnorm=I=-14:TP=-1.2:LRA=8:print_format=summary", "-codec:a", "libmp3lame", "-b:a", "320k", os.path.join(OUT, "rap_acapella.mp3")])

# separated stems (pre-master, same balance as mix)
stems = {
    "01_vocal": vocal_stem,
    "02_drums": drums * .85,
    "03_808_bass": bass_bus * .60,
    "04_music": music_bus * .46,
    "05_fx_samples": fx_bus * .48,
}
stem_dir = os.path.join(WORK, "stems"); os.makedirs(stem_dir, exist_ok=True)
for name, x in stems.items():
    x = x * fade_env.astype(np.float32)[:, None]
    sf.write(os.path.join(stem_dir, name + ".flac"), x, SR, subtype="PCM_24")
with zipfile.ZipFile(os.path.join(OUT, "rap_stems_flac.zip"), "w", zipfile.ZIP_DEFLATED) as z:
    for name in stems:
        z.write(os.path.join(stem_dir, name + ".flac"), arcname=name + ".flac")

print("DONE", master_mp3, "duration", N / SR)
