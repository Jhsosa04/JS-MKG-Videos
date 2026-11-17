#!/usr/bin/env python3
"""
JS MKG · Editor de videos para clientes (reels 9:16)
====================================================
Replica el estilo "talking head + motion graphics" del video de referencia:
  - cortes de silencios (jump cuts) y zoom alterno
  - subtitulos animados palabra por palabra con palabras clave resaltadas
  - etiquetas tipo "PASO 1"
  - panel superior (pantalla dividida) con imagen + titulo
  - insertos (stickers / capturas) que aparecen con pop
  - CTA final "COMENTA: PALABRA" con efecto de escritura
  - musica de fondo con ducking y volumen normalizado para Instagram
  - perfiles de estilo por cliente sacados de 5 videos de referencia

Comandos:
  python3 editor.py analizar  VIDEO [--salida DIR]
  python3 editor.py estilo    CLIENTE --refs v1.mp4 v2.mp4 ... [--salida estilos/]
  python3 editor.py preparar  VIDEO --salida DIR [--sin-cortes]
  python3 editor.py editar    DIR/preparado.mp4 --plan plan.json --estilo estilos/cliente.json -o final.mp4
"""
import argparse, json, os, re, subprocess, sys, unicodedata, wave, shutil, tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

BASE = Path(__file__).resolve().parent
FUENTES = BASE / "fonts"
MODELO = Path(os.environ.get("WHISPER_MODEL", BASE / "modelo-whisper"))
W, H, FPS = 1080, 1920, 30

ESTILO_BASE = {
    "cliente": "base",
    "fuente": "Bebas Neue",
    "archivo_fuente": "BebasNeue-Regular.ttf",
    "color_texto": "#FFFFFF",
    "color_acento": "#E9574B",
    "color_panel": "#F7EEEB",
    "color_oscuro": "#181717",
    "tam_subtitulo": 96,
    "tam_resaltado": 150,
    "subtitulo_y": 0.60,        # posicion vertical (0 arriba, 1 abajo)
    "palabras_por_grupo": 3,
    "zoom_alterno": 1.12,       # 1.0 para desactivar
    "alto_panel": 0.34,         # fraccion de la pantalla usada por el panel superior
    "mayusculas": True,         # False = respeta mayusculas/minusculas (estilo "If the *Prospects*")
    "volumen_musica": 0.12,
    "lufs": -14,
}

# ----------------------------------------------------------------- utilidades
def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        sys.exit(f"Error ejecutando: {' '.join(map(str, cmd))[:300]}\n{r.stderr[-2000:]}")
    return r

def duracion(video):
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)])
    return float(r.stdout.strip())

def hex2rgb(h):
    h = h.lstrip("#"); return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))

def hex2ass(h, alpha="00"):
    r, g, b = hex2rgb(h); return f"&H{alpha}{b:02X}{g:02X}{r:02X}"

def norm(s):
    s = unicodedata.normalize("NFD", s.lower())
    return re.sub(r"[^a-z0-9ñ]", "", "".join(c for c in s if unicodedata.category(c) != "Mn"))

def cargar_estilo(ruta):
    est = dict(ESTILO_BASE)
    if ruta: est.update(json.loads(Path(ruta).read_text()))
    return est

def fuente(est, tam):
    return ImageFont.truetype(str(FUENTES / est["archivo_fuente"]), tam)

# ----------------------------------------------------------------- audio / transcripcion
def extraer_audio(video, wav):
    run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-ac", "1", "-ar", "16000", str(wav)])

def transcribir(video):
    """Devuelve lista de segmentos con palabras y tiempos (faster-whisper)."""
    from faster_whisper import WhisperModel
    if not (MODELO / "model.bin").exists():
        sys.exit(f"Falta el modelo de Whisper en {MODELO}. Ejecuta setup.sh")
    with tempfile.TemporaryDirectory() as td:
        wav = Path(td) / "a.wav"; extraer_audio(video, wav)
        w = wave.open(str(wav))
        audio = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
    modelo = WhisperModel(str(MODELO), device="cpu", compute_type="int8")
    segs, _ = modelo.transcribe(audio, language="es", word_timestamps=True, vad_filter=False)
    out = []
    for s in segs:
        out.append({"inicio": round(s.start, 2), "fin": round(s.end, 2), "texto": s.text.strip(),
                    "palabras": [{"p": x.word.strip(), "i": round(x.start, 2), "f": round(x.end, 2)} for x in s.words]})
    return out

def detectar_silencios(video, umbral_db=-35, minimo=0.45):
    r = subprocess.run(["ffmpeg", "-v", "info", "-i", str(video), "-af",
                        f"silencedetect=noise={umbral_db}dB:d={minimo}", "-f", "null", "-"],
                       capture_output=True, text=True)
    ini = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", r.stderr)]
    fin = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", r.stderr)]
    return list(zip(ini, fin + [duracion(video)] * (len(ini) - len(fin))))

def tramos_con_voz(video, margen=0.12):
    total = duracion(video); tramos, cur = [], 0.0
    for a, b in detectar_silencios(video):
        if a - cur > 0.05: tramos.append((max(0, cur - margen), min(total, a + margen)))
        cur = b
    if total - cur > 0.05: tramos.append((max(0, cur - margen), total))
    return tramos

# ----------------------------------------------------------------- 1. analizar
def cmd_analizar(a):
    video = Path(a.video); out = Path(a.salida or f"analisis_{video.stem}"); out.mkdir(parents=True, exist_ok=True)
    dur = duracion(video)
    r = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,r_frame_rate",
             "-of", "json", str(video)])
    meta = json.loads(r.stdout)["streams"][0]
    # cortes de escena
    r = subprocess.run(["ffmpeg", "-i", str(video), "-vf", "select='gt(scene,0.25)',showinfo", "-f", "null", "-"],
                       capture_output=True, text=True)
    cortes = [round(float(x), 2) for x in re.findall(r"pts_time:([\d.]+)", r.stderr)]
    # hoja de contacto (1 cuadro por segundo)
    cols = 8; filas = int(np.ceil(dur / cols))
    run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-vf", f"fps=1,scale=200:-1,tile={cols}x{filas}",
         "-frames:v", "1", str(out / "hoja_contacto.jpg")])
    trans = transcribir(video)
    pal = paleta(video)
    silencios = detectar_silencios(video)
    inf = {"video": video.name, "duracion": round(dur, 2), "resolucion": f"{meta['width']}x{meta['height']}",
           "cortes_escena": cortes, "cortes_por_minuto": round(len(cortes) / dur * 60, 1),
           "silencios": [[round(x, 2), round(y, 2)] for x, y in silencios],
           "paleta": pal, "gancho_3s": " ".join(p["p"] for s in trans for p in s["palabras"] if p["i"] < 3),
           "transcripcion": trans}
    (out / "informe.json").write_text(json.dumps(inf, ensure_ascii=False, indent=1))
    (out / "transcripcion.txt").write_text("\n".join(f"[{s['inicio']:6.2f}-{s['fin']:6.2f}] {s['texto']}" for s in trans))
    print(f"Analisis listo en {out}/ (informe.json, transcripcion.txt, hoja_contacto.jpg)")

def paleta(video, n=6):
    with tempfile.TemporaryDirectory() as td:
        run(["ffmpeg", "-v", "error", "-i", str(video), "-vf", "fps=0.5,scale=96:-1", f"{td}/f%03d.png"])
        px = np.concatenate([np.asarray(Image.open(f).convert("RGB")).reshape(-1, 3) for f in sorted(Path(td).glob("*.png"))])
    px = px[np.random.default_rng(0).choice(len(px), min(40000, len(px)), replace=False)].astype(float)
    c = px[np.linspace(0, len(px) - 1, n).astype(int)]
    for _ in range(15):  # k-means simple
        lab = ((px[:, None] - c[None]) ** 2).sum(-1).argmin(1)
        c = np.array([px[lab == k].mean(0) if (lab == k).any() else c[k] for k in range(n)])
    cnt = np.bincount(lab, minlength=n); orden = cnt.argsort()[::-1]
    return [{"hex": "#%02X%02X%02X" % tuple(int(v) for v in c[k]), "peso": round(cnt[k] / cnt.sum(), 3)} for k in orden]

# ----------------------------------------------------------------- 2. estilo por cliente
def cmd_estilo(a):
    est = dict(ESTILO_BASE); est["cliente"] = a.cliente
    colores, ritmo = [], []
    for v in a.refs:
        colores += paleta(v, 12)
        r = subprocess.run(["ffmpeg", "-i", v, "-vf", "select='gt(scene,0.25)',showinfo", "-f", "null", "-"],
                           capture_output=True, text=True)
        ritmo.append(len(re.findall(r"pts_time", r.stderr)) / duracion(v) * 60)
    def sat(h):
        r, g, b = [x / 255 for x in hex2rgb(h)]; mx, mn = max(r, g, b), min(r, g, b)
        return (mx - mn) * (mx > 0.25)
    def luz(h): return sum(hex2rgb(h)) / 765
    vivos = sorted([c for c in colores if c["peso"] > 0.004], key=lambda c: sat(c["hex"]) ** 2 * c["peso"] ** 0.25, reverse=True)
    if vivos and sat(vivos[0]["hex"]) > 0.35: est["color_acento"] = vivos[0]["hex"]
    claros = [c for c in colores if luz(c["hex"]) > 0.82]
    if claros: est["color_panel"] = max(claros, key=lambda c: c["peso"])["hex"]
    est["referencias"] = [Path(v).name for v in a.refs]
    est["cortes_por_minuto_refs"] = round(float(np.mean(ritmo)), 1) if ritmo else None
    est["paleta_detectada"] = sorted({c["hex"] for c in colores})
    out = Path(a.salida or "estilos"); out.mkdir(parents=True, exist_ok=True)
    (out / f"{a.cliente}.json").write_text(json.dumps(est, ensure_ascii=False, indent=1))
    print(f"Estilo guardado en {out}/{a.cliente}.json  (acento {est['color_acento']}, panel {est['color_panel']})")

# ----------------------------------------------------------------- 3. preparar (normalizar + jump cuts + transcribir)
def cmd_preparar(a):
    video = Path(a.video); out = Path(a.salida); out.mkdir(parents=True, exist_ok=True)
    norm_v = out / "preparado.mp4"
    vf = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS},setsar=1"
    if a.sin_cortes:
        tramos = [(0, duracion(video))]
        run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-vf", vf, "-c:v", "libx264", "-preset", "veryfast",
             "-crf", "18", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", str(norm_v)])
    else:
        tramos = tramos_con_voz(video)
        sel = "+".join(f"between(t,{x:.3f},{y:.3f})" for x, y in tramos)
        run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-filter_complex",
             f"[0:v]select='{sel}',setpts=N/FRAME_RATE/TB,{vf}[v];[0:a]aselect='{sel}',asetpts=N/SR/TB[a]",
             "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
             "-c:a", "aac", "-b:a", "192k", "-ar", "48000", str(norm_v)])
    # puntos de corte en la linea de tiempo nueva (para el zoom alterno)
    cortes, acc = [], 0.0
    for x, y in tramos[:-1]:
        acc += y - x; cortes.append(round(acc, 3))
    trans = transcribir(norm_v)
    (out / "transcripcion.json").write_text(json.dumps({"cortes": cortes, "segmentos": trans}, ensure_ascii=False, indent=1))
    (out / "transcripcion.txt").write_text("\n".join(f"[{s['inicio']:6.2f}-{s['fin']:6.2f}] {s['texto']}" for s in trans))
    print(f"Preparado: {norm_v} ({duracion(video):.1f}s -> {duracion(norm_v):.1f}s, {len(cortes)} cortes)")

# ----------------------------------------------------------------- 3b. unir tomas
def tiene_voz(video):
    """True si Whisper (con filtro de voz) encuentra palabras en la toma."""
    from faster_whisper import WhisperModel
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
                         capture_output=True).stdout
    audio = np.frombuffer(raw, np.int16).astype(np.float32) / 32768
    modelo = WhisperModel(str(MODELO), device="cpu", compute_type="int8")
    segs, _ = modelo.transcribe(audio, language="es", vad_filter=True)
    texto = " ".join(s.text for s in segs).strip()
    return len(re.findall(r"\w+", texto)) >= 3

def cmd_unir(a):
    """Une tomas grabadas por separado en orden de nombre (01_, 02_, 03a_, 03b_...).
    Tomas con voz: se les quitan los silencios. Tomas sin voz (b-roll): se dejan con el audio bajo.
    Si hay varias tomas con el mismo numero (03a, 03b) se usa la ultima."""
    tomas = sorted(Path(t) for t in a.tomas)
    grupos = {}
    for t in tomas:
        m = re.match(r"(\d+)", t.stem); grupos[m.group(1) if m else t.stem] = t
    tomas = [grupos[k] for k in sorted(grupos)]
    out = Path(a.salida); out.mkdir(parents=True, exist_ok=True)
    tmp = out / "_tomas"; tmp.mkdir(exist_ok=True)
    forzar_broll = {Path(x).stem for x in (a.broll or [])}
    vf = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS},setsar=1,format=yuv420p"
    partes, cortes, acc, info = [], [], 0.0, []
    for t in tomas:
        broll = t.stem in forzar_broll or not tiene_voz(t)
        dest = tmp / f"{t.stem}.mp4"
        if broll:
            d = min(duracion(t), a.max_broll)
            run(["ffmpeg", "-y", "-v", "error", "-i", str(t), "-t", f"{d:.3f}", "-vf", vf,
                 "-af", f"volume={a.vol_broll},aresample=48000,aformat=channel_layouts=stereo",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "aac", "-b:a", "192k", str(dest)])
            internos = []
        else:
            tramos = tramos_con_voz(t)
            sel = "+".join(f"between(t,{x:.3f},{y:.3f})" for x, y in tramos)
            run(["ffmpeg", "-y", "-v", "error", "-i", str(t), "-filter_complex",
                 f"[0:v]select='{sel}',setpts=N/FRAME_RATE/TB,{vf}[v];"
                 f"[0:a]aselect='{sel}',asetpts=N/SR/TB,aresample=48000,aformat=channel_layouts=stereo[a]",
                 "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                 "-c:a", "aac", "-b:a", "192k", str(dest)])
            internos, s = [], 0.0
            for x, y in tramos[:-1]:
                s += y - x; internos.append(s)
        d = duracion(dest)
        cortes += [round(acc + c, 3) for c in internos]
        info.append({"toma": t.name, "tipo": "b-roll" if broll else "voz", "inicio": round(acc, 2), "fin": round(acc + d, 2)})
        acc += d
        cortes.append(round(acc, 3))
        partes.append(dest)
    cortes = cortes[:-1]
    lista = tmp / "lista.txt"
    lista.write_text("".join(f"file '{p.resolve()}'\n" for p in partes))
    prep = out / "preparado.mp4"
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lista), "-c:v", "libx264",
         "-preset", "veryfast", "-crf", "18", "-c:a", "aac", "-b:a", "192k", str(prep)])
    trans = transcribir(prep)
    (out / "transcripcion.json").write_text(json.dumps({"cortes": cortes, "tomas": info, "segmentos": trans},
                                                       ensure_ascii=False, indent=1))
    (out / "transcripcion.txt").write_text(
        "\n".join(f"TOMA {i['toma']} ({i['tipo']}) {i['inicio']}-{i['fin']}s" for i in info) + "\n\n" +
        "\n".join(f"[{s['inicio']:6.2f}-{s['fin']:6.2f}] {s['texto']}" for s in trans))
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"Unidas {len(partes)} tomas -> {prep} ({duracion(prep):.1f}s)")
    for i in info: print(f"  {i['toma']:20s} {i['tipo']:7s} {i['inicio']:6.2f}-{i['fin']:6.2f}")

# ----------------------------------------------------------------- 4. editar
def palabras_de(trans):
    return [p for s in trans["segmentos"] for p in s["palabras"] if p["p"]]

def resolver_tiempo(v, palabras, por_defecto=None):
    """Acepta segundos o {"frase": "texto dicho"} (+ "desfase") y devuelve segundos."""
    if v is None: return por_defecto
    if isinstance(v, (int, float)): return float(v)
    if isinstance(v, str) and re.fullmatch(r"[\d.]+", v): return float(v)
    frase = v["frase"] if isinstance(v, dict) else v
    obj = [norm(x) for x in frase.split() if norm(x)]
    toks = [norm(p["p"]) for p in palabras]
    for i in range(len(toks)):
        if toks[i:i + len(obj)] == obj:
            dic = v if isinstance(v, dict) else {}
            t = palabras[i + len(obj) - 1]["f"] if dic.get("al_terminar") else palabras[i]["i"]
            return t + dic.get("desfase", 0)
    sys.exit(f"No encontre la frase '{frase}' en la transcripcion")

def ass_tiempo(t):
    t = max(0, t); h = int(t // 3600); m = int(t % 3600 // 60); s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"

def crear_subtitulos_palabra(palabras, est, ruta, ocultar=()):
    """Una palabra a la vez, letra delgada y discreta (estilo tour de lujo)."""
    y = int(H * est["subtitulo_y"])
    cab = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: P,{est.get('fuente_sub', 'Montserrat Medium')},{est.get('tam_palabra', 46)},{hex2ass(est['color_texto'], est.get('alpha_sub', '18'))},&H000000FF,&HC0000000,&H70000000,0,0,0,0,100,100,1,0,1,1,3,5,40,40,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lineas = []
    for k, p in enumerate(palabras):
        ini = p["i"]
        fin = max(p["f"], ini + 0.25)
        if k + 1 < len(palabras): fin = min(fin + 0.25, palabras[k + 1]["i"])
        if any(a <= ini < b for a, b in ocultar) or fin - ini < 0.05: continue
        txt = p["p"].strip(".,;:¡!¿?")
        if est.get("mayusculas"): txt = txt.upper()
        lineas.append(f"Dialogue: 0,{ass_tiempo(ini)},{ass_tiempo(fin)},P,,0,0,0,,{{\\pos({W // 2},{y})\\fad(60,60)}}{txt}")
    Path(ruta).write_text(cab + "\n".join(lineas) + "\n", encoding="utf-8")

def crear_titulos(titulos, est, ruta, T):
    """Titulos grandes arriba, linea por linea, que entran con desenfoque y salen difuminandose.
    Cada linea: {"texto": "...", "tam": 120, "color": "blanco" | "acento" | "gris" | "#hex"}"""
    fuente_t = est.get("fuente_titulo", est["fuente"])
    cab = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: T,{fuente_t},100,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,-1,0,1,0,0,8,40,40,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = []
    for tit in titulos:
        x0, x1 = T(tit["inicio"]), T(tit.get("fin"))
        y = int(H * tit.get("y", est.get("titulo_y", 0.08)))
        for k, ln in enumerate(tit["lineas"]):
            if isinstance(ln, str): ln = {"texto": ln}
            tam = ln.get("tam", 110)
            ft = FUENTES / est.get("archivo_fuente_titulo", est["archivo_fuente"])
            while tam > 30 and ImageFont.truetype(str(ft), tam).getlength(ln["texto"]) > W - 120:
                tam -= 4  # que nunca se salga de la pantalla
            col = ln.get("color", "blanco")
            alpha = "00"
            if col == "acento": c = est["color_acento"]
            elif col == "gris": c, alpha = "#FFFFFF", est.get("alpha_gris", "48")
            elif col == "blanco": c = "#FFFFFF"
            else: c = col
            t0 = x0 + k * tit.get("escalon", 0.18)
            dur_ms = int((x1 - t0) * 1000)
            ent = f"\\move({W // 2},{y + 30},{W // 2},{y},0,260)\\blur16\\alpha&HFF&\\t(0,260,\\blur0\\alpha&H{alpha}&)"
            sal = f"\\t({dur_ms - 220},{dur_ms},\\blur14\\alpha&HFF&)"
            sombra = (f"Dialogue: 0,{ass_tiempo(t0)},{ass_tiempo(x1)},T,,0,0,0,,{{\\fs{tam}\\c&H000000&\\move({W // 2},{y + 36},{W // 2},{y + 6},0,260)"
                      f"\\blur16\\alpha&HFF&\\t(0,260,\\blur9\\alpha&H{est.get('alpha_sombra', '58')}&){sal}}}{ln['texto']}")
            ev.append(sombra)
            ev.append(f"Dialogue: 1,{ass_tiempo(t0)},{ass_tiempo(x1)},T,,0,0,0,,{{\\fs{tam}\\c{hex2ass(c)}{ent}{sal}}}{ln['texto']}")
            y += int(tam * ln.get("interlineado", 0.92))
    Path(ruta).write_text(cab + "\n".join(ev) + "\n", encoding="utf-8")

def crear_subtitulos(palabras, est, resaltar, ruta, ocultar=()):
    """Subtitulos estilo reel: aparecen palabra por palabra con pop; las palabras clave van grandes y en color."""
    res = {norm(x) for x in resaltar}
    y = int(H * est["subtitulo_y"])
    cab = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,{est['fuente']},{est['tam_subtitulo']},{hex2ass(est['color_texto'])},&H000000FF,&H00000000,&H78000000,0,0,0,0,100,100,1,0,1,0,4,5,60,60,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    # agrupar palabras
    grupos, g = [], []
    for i, p in enumerate(palabras):
        g.append(p)
        corta = i + 1 < len(palabras) and palabras[i + 1]["i"] - p["f"] > 0.35
        punto = p["p"][-1:] in ".,?!;:"
        if len(g) >= est["palabras_por_grupo"] or corta or punto or norm(p["p"]) in res or i == len(palabras) - 1:
            grupos.append(g); g = []
    lineas = []
    for k, g in enumerate(grupos):
        ini = g[0]["i"]
        fin = max(g[-1]["f"] + 0.15, ini + 0.5)
        if k + 1 < len(grupos): fin = min(fin, grupos[k + 1][0]["i"])
        if any(a <= ini < b for a, b in ocultar): continue
        partes = []
        for j, p in enumerate(g):
            txt = p["p"].strip(".,;:¡!")
            if est.get("mayusculas", True): txt = txt.upper()
            dt = int((p["i"] - ini) * 1000)
            if norm(p["p"]) in res:
                if j > 0: partes.append("\\N")
                partes.append(f"{{\\alpha&HFF&\\fs{est['tam_resaltado']}\\c{hex2ass(est['color_acento'])}\\fscx70\\fscy70"
                              f"\\t({dt},{dt + 120},\\alpha&H00&\\fscx108\\fscy108)\\t({dt + 120},{dt + 200},\\fscx100\\fscy100)}}{txt}"
                              f"{{\\fs{est['tam_subtitulo']}\\c{hex2ass(est['color_texto'])}}}")
            else:
                partes.append(f"{{\\alpha&HFF&\\fscx85\\fscy85\\t({dt},{dt + 90},\\alpha&H00&\\fscx100\\fscy100)}}{txt} ")
        lineas.append(f"Dialogue: 0,{ass_tiempo(ini)},{ass_tiempo(fin)},Sub,,0,0,0,,{{\\pos({W // 2},{y})}}" + "".join(partes))
    Path(ruta).write_text(cab + "\n".join(lineas) + "\n", encoding="utf-8")

def texto_con_acento(draw, xy, texto, f, est, ancla="la"):
    """Dibuja texto donde *palabras* entre asteriscos van con el color de acento."""
    x, y = xy; trozos = re.split(r"(\*[^*]+\*)", texto)
    total = sum(draw.textlength(t.strip("*"), font=f) for t in trozos)
    if ancla == "ma": x -= total / 2
    for t in trozos:
        acento = t.startswith("*")
        t = t.strip("*")
        draw.text((x, y), t, font=f, fill=hex2rgb(est["color_acento"] if acento else est.get("color_titulo_panel", est["color_oscuro"])))
        x += draw.textlength(t, font=f)

def png_panel(panel, est, ruta):
    """Panel superior: fondo claro + titulo (con *acento*) + imagen opcional."""
    ph = int(H * est["alto_panel"])
    img = Image.new("RGBA", (W, ph), hex2rgb(est["color_panel"]) + (255,))
    # brillo suave de color de acento
    glow = Image.new("RGBA", (W, ph), (0, 0, 0, 0)); gd = ImageDraw.Draw(glow)
    gd.ellipse((W * 0.25, ph * 0.25, W * 0.75, ph * 0.85), fill=hex2rgb(est["color_acento"]) + (40,))
    img = Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(90)))
    d = ImageDraw.Draw(img)
    titulo = panel.get("titulo", "")
    tiene_img = panel.get("imagen") and Path(panel["imagen"]).exists()
    if titulo:
        tam = panel.get("tam_titulo", 92 if tiene_img else 130)
        lineas = titulo.split("\n")
        # ajusta el tamano para que ninguna linea se salga de la pantalla
        while tam > 30 and max(d.textlength(l.replace("*", ""), font=fuente(est, tam)) for l in lineas) > W - 100:
            tam -= 4
        f = fuente(est, tam)
        y0 = 60 if tiene_img else (ph - len(lineas) * tam * 1.05) / 2
        for i, l in enumerate(lineas):
            texto_con_acento(d, (W / 2, y0 + i * tam * 1.05), l, f, est, ancla="ma")
    if tiene_img:
        im = Image.open(panel["imagen"]).convert("RGBA")
        top = 60 + (len(titulo.split("\n")) * 100 if titulo else 0) + 10
        maxw, maxh = W - 160, ph - top - 50
        im.thumbnail((maxw, maxh))
        # tarjeta con sombra y esquinas redondeadas
        mask = Image.new("L", im.size, 0); ImageDraw.Draw(mask).rounded_rectangle((0, 0, *im.size), 28, fill=255)
        x, y = (W - im.width) // 2, top + (maxh - im.height) // 2
        sombra = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(sombra).rounded_rectangle((x + 6, y + 12, x + im.width + 6, y + im.height + 12), 28, fill=(0, 0, 0, 70))
        img = Image.alpha_composite(img, sombra.filter(ImageFilter.GaussianBlur(14)))
        img.paste(im, (x, y), mask)
    img.save(ruta)
    return ph

def png_etiqueta(texto, est, ruta):
    f = fuente(est, 84)
    tmp = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    w = int(tmp.textlength(texto, font=f)) + 20
    img = Image.new("RGBA", (w + 20, 120), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
    sombra = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(sombra).text((14, 14), texto, font=f, fill=(0, 0, 0, 150))
    img = Image.alpha_composite(img, sombra.filter(ImageFilter.GaussianBlur(5)))
    ImageDraw.Draw(img).text((10, 10), texto, font=f, fill=hex2rgb(est["color_texto"]))
    img.save(ruta)

def pngs_cta(etiqueta, palabra, est, carpeta):
    """Caja de CTA tipo 'COMENTA: EDITAR' con efecto de escritura (un PNG por letra)."""
    bw, bh = 760, 210; rutas = []
    fe, fp = fuente(est, 50), fuente(est, 86)
    for n in range(1, len(palabra) + 1):
        img = Image.new("RGBA", (bw + 60, bh + 60), (0, 0, 0, 0))
        glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(glow).rounded_rectangle((20, 20, bw + 40, bh + 40), 34, fill=hex2rgb(est["color_acento"]) + (150,))
        img = Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(16)))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((30, 30, bw + 30, bh + 30), 30, fill=hex2rgb(est["color_acento"]), outline=(255, 255, 255), width=6)
        claro = sum(hex2rgb(est["color_acento"])) / 765 > 0.6
        d.text((62, 44), etiqueta, font=fe, fill=hex2rgb(est["color_oscuro"]) if claro else (255, 255, 255))
        d.rounded_rectangle((56, 104, bw + 4, bh + 8), 16, fill=(255, 255, 255))
        d.text(((bw + 60) / 2, 156), palabra[:n] + ("|" if n < len(palabra) else ""), font=fp, fill=hex2rgb(est["color_oscuro"]), anchor="mm")
        r = Path(carpeta) / f"cta_{n:02d}.png"; img.save(r); rutas.append(r)
    return rutas

COLOR = {
    "ninguno": "",
    "natural": "eq=contrast=1.06:saturation=1.12:gamma=0.98,unsharp=5:5:0.35",
    "cine": "eq=contrast=1.12:saturation=0.9:brightness=-0.015,"
            "colorbalance=rs=-0.04:gs=-0.01:bs=0.06:rh=0.06:gh=0.01:bh=-0.05,"
            "curves=master='0/0 0.25/0.21 0.75/0.8 1/1',vignette=angle=PI/5,unsharp=5:5:0.35",
    "calido": "eq=contrast=1.08:saturation=1.1,colorbalance=rm=0.05:bm=-0.05:rh=0.04:bh=-0.04,unsharp=5:5:0.35",
    "frio": "eq=contrast=1.08:saturation=0.95,colorbalance=rm=-0.03:bm=0.05:bh=0.03,unsharp=5:5:0.35",
    "vivo": "eq=contrast=1.1:saturation=1.3:gamma=0.97,unsharp=5:5:0.45",
    "luminoso": "eq=contrast=1.04:brightness=0.015:saturation=1.2:gamma=1.04,"
                "colorbalance=rm=0.02:bm=-0.01:rh=0.02:bh=-0.02,unsharp=5:5:0.4",
}

CLAVES_SFX = [  # (tipo, palabras en el nombre del archivo), se evalua en este orden
    ("ambiente", ["ambience", "ambiente"]),
    ("glitch", ["glitch"]),
    ("impacto", ["boom", "impact", "hit", "impacto"]),
    ("transicion", ["riser, transition, whoosh", "transition, whoosh", "transicion"]),
    ("riser", ["riser"]),
    ("swish", ["swish", "swipe"]),
    ("whoosh", ["whoosh", "swoosh"]),
    ("pop", ["pop", "bubbly"]),
    ("click", ["click", "tap", "button"]),
    ("ding", ["notification", "alert", "ding"]),
]
ALINEAR = {"whoosh": "pico", "swish": "pico", "transicion": "pico", "riser": "pico", "glitch": "inicio",
           "impacto": "inicio", "pop": "inicio", "click": "inicio", "ding": "inicio"}
_BIB = {}

def leer_audio(f, sr=48000):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(f), "-ac", "2", "-ar", str(sr), "-f", "s16le", "-"],
                         capture_output=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32).reshape(-1, 2) / 32768

def separar_variaciones(x, sr=48000, umbral_db=-34, hueco=0.12):
    """Archivos tipo 'Variations' traen varios sonidos seguidos: los separa por silencios."""
    env = np.abs(x).max(1); win = int(sr * 0.01)
    env = np.convolve(env, np.ones(win) / win, "same")
    activo = env > env.max() * 10 ** (umbral_db / 20)
    trozos, i, n = [], 0, len(x)
    while i < n:
        if not activo[i]: i += 1; continue
        j = i
        while j < n:
            k = j
            while k < n and not activo[k]: k += 1
            if k - j > sr * hueco or k >= n: break
            j = k + 1
            while j < n and activo[j]: j += 1
        a0, b0 = max(0, i - int(sr * 0.01)), min(n, j + int(sr * 0.05))
        if b0 - a0 > sr * 0.05: trozos.append(x[a0:b0])
        i = j + 1
    return trozos or [x]

def biblioteca_sfx(carpeta):
    """{tipo: [clips]} a partir de una carpeta de efectos del usuario (cualquier estructura de subcarpetas)."""
    if not carpeta or not Path(carpeta).is_dir(): return {}
    if str(carpeta) in _BIB: return _BIB[str(carpeta)]
    bib = {}
    for f in sorted(Path(carpeta).rglob("*")):
        if f.suffix.lower() not in (".wav", ".mp3", ".ogg", ".m4a", ".aif", ".aiff"): continue
        nombre = (f.parent.name + " " + f.stem).lower()
        tipo = next((t for t, ks in CLAVES_SFX if any(k in nombre for k in ks)), None)
        if not tipo or tipo == "ambiente": continue
        x = leer_audio(f)
        trozos = separar_variaciones(x) if ("variation" in nombre or tipo in ("whoosh", "swish", "click", "pop")) else [x]
        for t in trozos:
            if tipo in ("whoosh", "swish") and len(t) > 48000 * 2.2: continue  # demasiado largo para un barrido
            bib.setdefault(tipo, []).append((f.name, t))
    _BIB[str(carpeta)] = bib
    return bib

def archivos_sfx(tipo, carpeta_extra=None):
    return sorted((BASE / "sfx").glob(f"{tipo}*.wav"))

def pista_sfx(eventos, dur, ruta, vol_general=0.8, carpeta_extra=None):
    """Mezcla los efectos en una pista estereo. Usa la biblioteca del usuario si existe; rota variantes sin repetir."""
    sr = 48000; pista = np.zeros((int(dur * sr) + 2 * sr, 2), np.float32)
    rng = np.random.default_rng(11); ultimo = {}
    bib = biblioteca_sfx(carpeta_extra)
    respaldo = {"transicion": "whoosh", "glitch": "whoosh", "swish": "whoosh"}
    usados = []
    for e in sorted(eventos, key=lambda e: e["t"]):
        tipo = e.get("tipo"); clip = None
        if e.get("archivo"):
            clip = leer_audio(e["archivo"])
        else:
            ops = bib.get(tipo) or (bib.get(respaldo.get(tipo)) if respaldo.get(tipo) else None)
            if ops:
                ops2 = [o for o in ops if o[0] + str(len(o[1])) != ultimo.get(tipo)] or ops
                nom, clip = ops2[rng.integers(len(ops2))]; ultimo[tipo] = nom + str(len(clip))
            else:
                fs = archivos_sfx(tipo) or archivos_sfx(respaldo.get(tipo, tipo))
                if not fs: continue
                fs2 = [f for f in fs if str(f) != ultimo.get(tipo)] or fs
                f = fs2[rng.integers(len(fs2))]; ultimo[tipo] = str(f); clip = leer_audio(f); nom = f.name
        if clip is None or not len(clip): continue
        # alinear: el punto fuerte del sonido cae justo en t
        env = np.convolve(np.abs(clip).max(1), np.ones(480) / 480, "same")
        pico = int(np.argmax(env)) if ALINEAR.get(tipo, "inicio") == "pico" else int(np.argmax(env > env.max() * 0.1))
        i = int(e["t"] * sr) - pico
        if i < 0: clip = clip[-i:]; i = 0
        clip = clip / (np.abs(clip).max() + 1e-6) * 0.9
        n = min(len(clip), len(pista) - i)
        if n > 0:
            fade = np.ones(n, np.float32); m = min(n, int(sr * 0.03)); fade[-m:] = np.linspace(1, 0, m)
            pista[i:i + n] += clip[:n] * fade[:, None] * e.get("vol", 0.5) * vol_general
        usados.append(f"{e['t']:6.2f}s {tipo:10s} {nom if not e.get('archivo') else e['archivo']}")
    pista = np.tanh(pista[:int(dur * sr)])  # limitador suave
    with wave.open(str(ruta), "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(sr); w.writeframes((pista * 32767).astype(np.int16).tobytes())
    Path(ruta).with_suffix(".txt").write_text("\n".join(usados))

def buscar_media(ruta, extra=()):
    """Encuentra un archivo/carpeta de medios aunque la ruta sea de otra maquina (busca por nombre)."""
    if not ruta: return ruta
    if Path(ruta).exists(): return str(ruta)
    nombre = Path(str(ruta).replace("\\", "/")).name
    raices = [Path(os.environ.get("JSMKG_MEDIA", "/home/claude")), Path("/mnt/user-data/uploads"), *map(Path, extra)]
    for r in raices:
        if r.is_dir():
            for f in r.rglob(nombre):
                return str(f)
    return ruta

def cmd_editar(a):
    est = cargar_estilo(a.estilo)
    video = Path(a.video)
    plan = json.loads(Path(a.plan).read_text()) if a.plan else {}
    tjson = Path(a.transcripcion) if a.transcripcion else video.parent / "transcripcion.json"
    trans = json.loads(tjson.read_text()) if tjson.exists() else {"cortes": [], "segmentos": transcribir(video)}
    palabras = palabras_de(trans)
    # correcciones de palabras mal transcritas (ej. "Cloud" -> "Claude")
    # (las frases del plan se buscan en la transcripcion original; la correccion solo afecta a los subtitulos)
    corr = {norm(k): v for k, v in plan.get("correcciones", {}).items()}
    palabras_sub = []
    for p in palabras:
        q = dict(p); n = norm(p["p"])
        if n in corr: q["p"] = corr[n] + re.sub(r"^.*?([.,;:?!]*)$", r"\1", p["p"])
        palabras_sub.append(q)
    tmp = Path(tempfile.mkdtemp(prefix="edit_"))
    # --- velocidad general (1.08 = 8% mas rapido, sin cambiar el tono de voz)
    vel = float(plan.get("velocidad", est.get("velocidad", 1.0)))
    if abs(vel - 1) > 0.001:
        rapido = tmp / "rapido.mp4"
        run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-filter_complex",
             f"[0:v]setpts=PTS/{vel},fps={FPS}[v];[0:a]atempo={vel}[a]", "-map", "[v]", "-map", "[a]",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-c:a", "aac", "-b:a", "256k", str(rapido)])
        video = rapido
        for lista in (palabras, palabras_sub):
            for p in lista: p["i"] = round(p["i"] / vel, 3); p["f"] = round(p["f"] / vel, 3)
        trans["cortes"] = [c / vel for c in trans.get("cortes", [])]
        for tm in trans.get("tomas", []): tm["inicio"] /= vel; tm["fin"] /= vel
    dur = duracion(video)
    def T(v, d=None):
        if isinstance(v, (int, float)) or (isinstance(v, str) and re.fullmatch(r"[\d.]+", v)): return float(v) / vel
        return resolver_tiempo(v, palabras, d)
    entradas = ["-i", str(video)]; nin = 1; fc = []

    def nueva_imagen(ruta):
        nonlocal nin
        entradas.extend(["-loop", "1", "-framerate", str(FPS), "-t", f"{dur:.3f}", "-i", str(ruta)]); nin += 1
        return nin - 1

    # --- color + movimiento de camara
    #  * empuje lento en cada plano          * reencuadres automaticos cada N s (cortes falsos con otro nivel de zoom)
    #  * golpe de zoom en palabras/titulos   * sacudida + destello en titulos con "impacto"
    #  * transicion de barrido (zoom + desenfoque) entre tomas
    res_set = {norm(x) for x in plan.get("subtitulos", {}).get("resaltar", [])}
    t_clave = [p["i"] for p in palabras_sub if norm(p["p"]) in res_set]
    niveles = plan.get("niveles_zoom", est.get("niveles_zoom", [1.0, est.get("zoom_alterno", 1.1)]))
    empuje = plan.get("empuje", est.get("empuje", 0.05))
    golpe = plan.get("golpe_zoom", est.get("golpe_zoom", 0.08))
    cada = plan.get("reencuadre_cada", est.get("reencuadre_cada", 0))
    cortes = sorted(set([0.0] + [c for c in trans.get("cortes", []) if 0 < c < dur] + [dur]))
    trans_t = [x["inicio"] for x in trans.get("tomas", [])[1:]] if est.get("transicion", "ninguna") != "ninguna" else []
    trans_t += [T(x) for x in plan.get("transiciones", [])]
    planos = sorted(set(cortes + trans_t))
    if cada:
        extra = []
        for a0, b0 in zip(planos[:-1], planos[1:]):
            n = int((b0 - a0) // cada)
            if n >= 2: extra += [a0 + (b0 - a0) * k / n for k in range(1, n)]
        planos = sorted(set(planos + [round(x, 3) for x in extra]))
    reencuadres = [x for x in planos if x not in cortes and x not in trans_t]
    terminos = []
    for i in range(len(planos) - 1):
        a0, b0 = planos[i], planos[i + 1]
        s0 = niveles[i % len(niveles)]
        terminos.append(f"between(t,{a0:.3f},{b0:.3f})*({s0:.3f}+{empuje:.3f}*(t-{a0:.3f})/{max(b0 - a0, 0.1):.3f})")
    titulos = plan.get("titulos", [])
    t_impacto = [T(x["inicio"]) for x in titulos if x.get("impacto")] + [T(x) for x in plan.get("impactos", [])]
    golpes = [(ti, golpe) for ti in t_clave] + [(T(x["inicio"]), x.get("fuerza", golpe)) for x in plan.get("zooms", [])]
    golpes += [(T(x["inicio"]), est.get("golpe_titulo", 0.05) * (1.8 if x.get("impacto") else 1)) for x in titulos]
    for ti, g in golpes:
        sig = min([c for c in planos if c > ti + 0.05] + [ti + 1.4, dur])
        terminos.append(f"between(t,{ti:.3f},{sig:.3f})*{g:.3f}*min(1,(t-{ti:.3f})/0.08)")
    for c in trans_t:
        terminos.append(f"between(t,{c - 0.14:.3f},{c + 0.14:.3f})*0.16*(1-abs(t-{c:.3f})/0.14)")
    zexp = "+".join(terminos) or "1"
    # sacudida (necesita margen: el zoom minimo ya deja algunos pixeles a cada lado)
    amp = est.get("sacudida", 16)
    sx = "+".join(f"between(t,{ti:.3f},{ti + 0.35:.3f})*{amp}*sin(2*PI*23*(t-{ti:.3f}))*(1-(t-{ti:.3f})/0.35)" for ti in t_impacto) or "0"
    sy = "+".join(f"between(t,{ti:.3f},{ti + 0.35:.3f})*{amp}*cos(2*PI*19*(t-{ti:.3f}))*(1-(t-{ti:.3f})/0.35)" for ti in t_impacto) or "0"
    color = plan.get("color", est.get("color", "natural"))
    filtro_color = est.get("filtro_color") or COLOR.get(color, "")
    pre = (filtro_color + ",") if filtro_color else ""
    fc.append(f"[0:v]{pre}scale=w='2*trunc({W}*({zexp})/2)':h='2*trunc({H}*({zexp})/2)':eval=frame,"
              f"crop={W}:{H}:'clip((iw-{W})/2+({sx}),0,iw-{W})':'clip((ih-{H})*0.35+({sy}),0,ih-{H})',setsar=1[v0]")
    cur = "v0"
    if trans_t:
        en_d = "+".join(f"between(t,{c - 0.09:.3f},{c + 0.09:.3f})" for c in trans_t)
        en_g = "+".join(f"between(t,{c - 0.13:.3f},{c + 0.13:.3f})" for c in trans_t)
        fc.append(f"[{cur}]dblur=angle=0:radius=60:enable='{en_d}',gblur=sigma=7:enable='{en_g}'[v0t]"); cur = "v0t"
    if t_impacto and est.get("destello", True):
        en_f = "+".join(f"between(t,{ti:.3f},{ti + 0.07:.3f})" for ti in t_impacto)
        fc.append(f"[{cur}]eq=brightness=0.22:contrast=0.9:enable='{en_f}'[v0f]"); cur = "v0f"

    # --- paneles superiores (pantalla dividida)
    paneles = plan.get("paneles", [])
    ocultar_subs = []
    if paneles:
        ph = int(H * est["alto_panel"])
        rng = [(T(p["inicio"]), T(p.get("fin"), dur)) for p in paneles]
        en = "+".join(f"between(t,{x:.3f},{y:.3f})" for x, y in rng)
        bajo = H - ph
        fc.append(f"[{cur}]split[pa][pb];[pb]crop={W}:{bajo}:0:{int(H * 0.04)},pad={W}:{H}:0:{ph}:color={est['color_panel']}[ps0]")
        c2 = "ps0"
        for k, (p, (x, y)) in enumerate(zip(paneles, rng)):
            png_panel(p, est, tmp / f"panel{k}.png")
            idx = nueva_imagen(tmp / f"panel{k}.png")
            fc.append(f"[{idx}:v]format=rgba,fade=in:st={x:.3f}:d=0.25:alpha=1[pi{k}];"
                      f"[{c2}][pi{k}]overlay=0:'if(lt(t,{x + 0.3:.3f}),-40+40*(t-{x:.3f})/0.3,0)':enable='between(t,{x:.3f},{y:.3f})'[ps{k + 1}]")
            c2 = f"ps{k + 1}"
        fc.append(f"[pa][{c2}]overlay=0:0:enable='{en}'[v1]"); cur = "v1"

    # --- insertos (imagenes que aparecen con pop: capturas, logos, stickers)
    for k, ins in enumerate(plan.get("insertos", [])):
        x0, x1 = T(ins["inicio"]), T(ins.get("fin"), dur)
        ancho = int(ins.get("ancho", 0.4) * W)
        idx = nueva_imagen(ins["imagen"])
        px, py = int(ins.get("x", 0.5) * W), int(ins.get("y", 0.5) * H)
        fc.append(f"[{idx}:v]scale={ancho}:-1,format=rgba,fade=in:st={x0:.3f}:d=0.15:alpha=1[in{k}];"
                  f"[{cur}][in{k}]overlay={px}-w/2:'{py}-h/2+if(lt(t,{x0 + 0.2:.3f}),30*(1-(t-{x0:.3f})/0.2),0)'"
                  f":enable='between(t,{x0:.3f},{x1:.3f})'[vi{k}]")
        cur = f"vi{k}"

    # --- etiquetas tipo PASO 1
    for k, et in enumerate(plan.get("etiquetas", [])):
        x0, x1 = T(et["inicio"]), T(et.get("fin"), dur)
        png_etiqueta(et["texto"], est, tmp / f"et{k}.png")
        idx = nueva_imagen(tmp / f"et{k}.png")
        # si hay panel activo, la etiqueta baja debajo del panel
        y_pan = int(H * est["alto_panel"]) + 30
        en_pan = "+".join(f"between(t,{T(p['inicio']):.3f},{T(p['fin'], dur):.3f})" for p in paneles) or "0"
        fc.append(f"[{cur}][{idx}:v]overlay=30:'if({en_pan},{y_pan},150)':enable='between(t,{x0:.3f},{x1:.3f})'[ve{k}]")
        cur = f"ve{k}"

    # --- CTA final
    cta = plan.get("cta")
    if cta:
        x0, x1 = T(cta["inicio"]), T(cta.get("fin"), dur)
        if cta.get("ocultar_subtitulos", True): ocultar_subs.append((x0, x1))
        rutas = pngs_cta(cta.get("etiqueta", "COMENTA:"), cta["palabra"].upper(), est, tmp)
        paso = min(0.12, (x1 - x0) * 0.4 / len(rutas))
        for n, r in enumerate(rutas):
            idx = nueva_imagen(r)
            t0 = x0 + n * paso; t1 = x1 if n == len(rutas) - 1 else t0 + paso
            fc.append(f"[{cur}][{idx}:v]overlay=(W-w)/2:{int(H * 0.80)}-h/2:enable='between(t,{t0:.3f},{t1:.3f})'[vc{n}]")
            cur = f"vc{n}"

    # --- subtitulos
    sub = plan.get("subtitulos", {"activar": True})
    if sub.get("activar", True) and palabras:
        ass = tmp / "subs.ass"
        if est.get("modo_subtitulo", "grupos") == "palabra":
            crear_subtitulos_palabra(palabras_sub, est, ass, ocultar=ocultar_subs)
        else:
            crear_subtitulos(palabras_sub, est, sub.get("resaltar", []), ass, ocultar=ocultar_subs)
        fc.append(f"[{cur}]ass='{ass}':fontsdir='{FUENTES}'[vs]"); cur = "vs"
    if plan.get("titulos"):
        ass_t = tmp / "titulos.ass"
        crear_titulos(plan["titulos"], est, ass_t, lambda v: T(v, dur))
        fc.append(f"[{cur}]ass='{ass_t}':fontsdir='{FUENTES}'[vt]"); cur = "vt"
    fc.append(f"[{cur}]format=yuv420p[vout]")

    # --- efectos de sonido (pista generada con numpy)
    eventos = list(plan.get("sfx", []))
    if plan.get("sfx_auto", est.get("sfx_auto", True)):
        for c in trans_t:                                   # barrido entre tomas
            eventos.append({"tipo": "transicion", "t": c, "vol": 0.55})
        for k, tit in enumerate(titulos):                   # cada titulo entra con aire/whoosh (alternando)
            t0 = T(tit["inicio"])
            if tit.get("impacto"):
                eventos.append({"tipo": "impacto", "t": t0, "vol": 0.6})
                if t0 > 1.5: eventos.append({"tipo": "riser", "t": t0, "vol": 0.35})
            else:
                eventos.append({"tipo": "whoosh" if k % 2 == 0 else "swish", "t": t0 + 0.05, "vol": 0.4})
        for x in plan.get("impactos", []):
            eventos.append({"tipo": "impacto", "t": T(x), "vol": 0.55})
        if est.get("sfx_reencuadre", False):
            eventos += [{"tipo": "click", "t": r, "vol": 0.2} for r in reencuadres]
        for p_ in paneles:
            eventos.append({"tipo": "whoosh", "t": T(p_["inicio"]), "vol": 0.45})
        for ins in plan.get("insertos", []):
            eventos.append({"tipo": "pop", "t": T(ins["inicio"]), "vol": 0.45})
        if est.get("sfx_palabras", False):
            eventos += [{"tipo": "pop", "t": ti, "vol": 0.25} for ti in t_clave]
        if cta:
            x0c = T(cta["inicio"]); paso_c = min(0.12, (T(cta.get("fin"), dur) - x0c) * 0.4 / max(1, len(cta["palabra"])))
            eventos.append({"tipo": "whoosh", "t": x0c, "vol": 0.45})
            eventos += [{"tipo": "click", "t": x0c + n * paso_c, "vol": 0.4} for n in range(len(cta["palabra"]))]
            eventos.append({"tipo": "ding", "t": x0c + len(cta["palabra"]) * paso_c, "vol": 0.3})
    sfx_wav = None
    if eventos:
        sfx_wav = tmp / "sfx.wav"; pista_sfx(eventos, dur, sfx_wav, est.get("volumen_sfx", 0.8), buscar_media(est.get("carpeta_sfx") or "Efectos de Sonido"))
        entradas.extend(["-i", str(sfx_wav)]); si = nin; nin += 1

    # --- audio: voz + efectos + musica con ducking, normalizado para Instagram
    mus = plan.get("musica")
    if mus: mus = dict(mus, archivo=buscar_media(mus["archivo"]))
    lufs = est["lufs"]
    mezcla = ["[voz]"]; partes_a = ["[0:a]asplit[voz][vsc]"]
    if sfx_wav: mezcla.append(f"[{si}:a]")
    if mus and Path(mus["archivo"]).exists() and mus.get("segmentos"):
        # arma la musica con tramos (para alargar una cancion corta repitiendo su parte central sin que se note)
        sr = 48000; base_m = leer_audio(mus["archivo"]); trozos = []
        for a_, b_ in mus["segmentos"]:
            x = base_m[int(a_ * sr): int(b_ * sr) if b_ else len(base_m)].copy()
            m = int(sr * 0.025); x[:m] *= np.linspace(0, 1, m)[:, None]; x[-m:] *= np.linspace(1, 0, m)[:, None]
            trozos.append(x)
        mezcla_m = np.concatenate(trozos)
        mus = dict(mus, archivo=str(tmp / "musica_armada.wav"), desde=mus.get("desde", 0))
        with wave.open(mus["archivo"], "wb") as w:
            w.setnchannels(2); w.setsampwidth(2); w.setframerate(sr)
            w.writeframes((np.clip(mezcla_m, -1, 1) * 32767).astype(np.int16).tobytes())
    if mus and Path(mus["archivo"]).exists():
        entradas.extend(["-stream_loop", "-1", "-i", mus["archivo"]]); mi = nin; nin += 1
        vol = mus.get("volumen", est["volumen_musica"]); ini_m = mus.get("desde", 0)
        partes_a.append(f"[{mi}:a]atrim={ini_m}:{ini_m + dur:.3f},asetpts=PTS-STARTPTS,aresample=48000,"
                        f"aformat=channel_layouts=stereo,volume={vol},afade=t=in:d=0.4,"
                        f"afade=t=out:st={max(0, dur - 1.5):.3f}:d=1.5[m0]")
        partes_a.append("[m0][vsc]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=350[mduck]")
        mezcla.append("[mduck]")
    else:
        partes_a.append("[vsc]anullsink")
    partes_a.append(f"{''.join(mezcla)}amix=inputs={len(mezcla)}:duration=first:normalize=0,"
                    f"loudnorm=I={lufs}:TP=-1.5:LRA=11[aout]")
    fc.extend(partes_a)

    salida = Path(a.salida); salida.parent.mkdir(parents=True, exist_ok=True)
    (tmp / "filtro.txt").write_text(";".join(fc))
    run(["ffmpeg", "-y", "-v", "error", *entradas, "-filter_complex_script", str(tmp / "filtro.txt"),
         "-map", "[vout]", "-map", "[aout]", "-t", f"{dur:.3f}", "-r", str(FPS),
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-profile:v", "high",
         "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(salida)])
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"Video final: {salida} ({dur:.1f}s, {W}x{H})")

# ----------------------------------------------------------------- CLI
def main():
    ap = argparse.ArgumentParser(description="Editor de videos JS MKG")
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("analizar"); p.add_argument("video"); p.add_argument("--salida"); p.set_defaults(f=cmd_analizar)
    p = sp.add_parser("estilo"); p.add_argument("cliente"); p.add_argument("--refs", nargs="+", required=True)
    p.add_argument("--salida"); p.set_defaults(f=cmd_estilo)
    p = sp.add_parser("preparar"); p.add_argument("video"); p.add_argument("--salida", required=True)
    p.add_argument("--sin-cortes", action="store_true"); p.set_defaults(f=cmd_preparar)
    p = sp.add_parser("unir"); p.add_argument("tomas", nargs="+"); p.add_argument("--salida", required=True)
    p.add_argument("--broll", nargs="*", help="tomas sin voz (si no se indica, se detecta solo)")
    p.add_argument("--max-broll", type=float, default=4.0); p.add_argument("--vol-broll", type=float, default=0.25)
    p.set_defaults(f=cmd_unir)
    p = sp.add_parser("editar"); p.add_argument("video"); p.add_argument("--plan"); p.add_argument("--estilo")
    p.add_argument("--transcripcion"); p.add_argument("-o", "--salida", required=True); p.set_defaults(f=cmd_editar)
    a = ap.parse_args(); a.f(a)

if __name__ == "__main__":
    main()
