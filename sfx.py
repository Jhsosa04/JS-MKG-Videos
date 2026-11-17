#!/usr/bin/env python3
"""Genera la biblioteca de efectos de sonido del editor (sin derechos de autor: todo es sintetizado).
Uso: python3 -I sfx.py  -> crea sfx/*.wav"""
from pathlib import Path
import numpy as np, wave

SR = 48000
OUT = Path(__file__).resolve().parent / "sfx"
rng = np.random.default_rng(7)

def guardar(nombre, x):
    x = x / (np.abs(x).max() + 1e-9) * 0.89
    st = np.stack([x, x], 1) if x.ndim == 1 else x
    OUT.mkdir(exist_ok=True)
    with wave.open(str(OUT / f"{nombre}.wav"), "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((st * 32767).astype(np.int16).tobytes())

def env(n, ataque, caida):
    t = np.arange(n) / SR
    return np.minimum(1, t / max(ataque, 1e-4)) * np.exp(-np.maximum(0, t - ataque) / caida)

def filtro_paso_banda(x, f_ini, f_fin, q=2.0):
    """Barrido de filtro resonante (state-variable) de f_ini a f_fin."""
    n = len(x); f = np.geomspace(f_ini, f_fin, n); y = np.zeros(n); lp = bp = 0.0
    for i in range(n):
        g = 2 * np.sin(np.pi * f[i] / SR)
        hp = x[i] - lp - bp / q; bp += g * hp; lp += g * bp; y[i] = bp
    return y

def whoosh(d=0.45, sube=True):
    n = int(SR * d); t = np.arange(n) / n
    ruido = rng.standard_normal(n)
    y = filtro_paso_banda(ruido, 300 if sube else 4000, 4000 if sube else 300, q=1.6)
    forma = np.sin(np.pi * t) ** 1.5
    izq, der = y * forma * (1 - 0.6 * t), y * forma * (0.4 + 0.6 * t)  # paneo de izquierda a derecha
    return np.stack([izq, der], 1)

def pop(d=0.12):
    n = int(SR * d); t = np.arange(n) / SR
    f = 900 * np.exp(-t * 25) + 380
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * env(n, 0.002, 0.03)

def click(d=0.04):
    n = int(SR * d)
    return (rng.standard_normal(n) * 0.6 + np.sin(2 * np.pi * 2400 * np.arange(n) / SR)) * env(n, 0.0005, 0.006)

def impacto(d=1.2):
    n = int(SR * d); t = np.arange(n) / SR
    f = 120 * np.exp(-t * 6) + 42
    sub = np.sin(2 * np.pi * np.cumsum(f) / SR) * env(n, 0.003, 0.35)
    golpe = filtro_paso_banda(rng.standard_normal(n), 2500, 200, 1.2) * env(n, 0.001, 0.05)
    return sub + 0.5 * golpe

def riser(d=1.0):
    n = int(SR * d); t = np.arange(n) / n
    tono = np.sin(2 * np.pi * np.cumsum(200 + 900 * t ** 2) / SR)
    aire = filtro_paso_banda(rng.standard_normal(n), 400, 6000, 2.5)
    return (0.4 * tono + aire) * t ** 2

def ding(d=0.8):
    n = int(SR * d); t = np.arange(n) / SR
    return sum(a * np.sin(2 * np.pi * f * t) for f, a in [(1318, 1), (2637, 0.4), (3951, 0.15)]) * env(n, 0.002, 0.18)

def swish(d=0.22):
    n = int(SR * d); t = np.arange(n) / n
    y = filtro_paso_banda(rng.standard_normal(n), 2500, 7000, q=1.2)
    return y * np.sin(np.pi * t) ** 2

if __name__ == "__main__":
    # variantes para que no suene repetitivo
    for k in range(6):
        d = rng.uniform(0.3, 0.6); sube = bool(k % 2 == 0)
        x = whoosh(d, sube)
        if k % 3 == 1: x = x[:, ::-1]  # cambia el paneo
        guardar(f"whoosh_{k + 1}", x)
    for k in range(4):
        guardar(f"swish_{k + 1}", swish(rng.uniform(0.15, 0.3)))
    for k in range(3):
        guardar(f"pop_{k + 1}", pop(rng.uniform(0.08, 0.15)))
    guardar("impacto_2", impacto(0.9))
    guardar("whoosh", whoosh()); guardar("whoosh_corto", whoosh(0.28)); guardar("whoosh_baja", whoosh(0.45, False))
    guardar("pop", pop()); guardar("click", click()); guardar("impacto", impacto())
    guardar("riser", riser()); guardar("ding", ding())
    print("Efectos creados en", OUT)
