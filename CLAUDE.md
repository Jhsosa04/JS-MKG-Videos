# Editor de videos JS MKG — instrucciones para Claude

Este repo es el editor de reels 9:16 de la agencia JS MKG (Jhon Sosa). Claude lo ejecuta en su espacio de trabajo y edita los videos de los clientes.

## Preparar (una vez por sesión)
```bash
bash setup.sh            # instala faster-whisper, baja el modelo Whisper small (npm) y genera sfx/
```
Ejecuta Python siempre con `python3 -I editor.py ...`.

## Forma de trabajo: SOLO GitHub (decisión de Jhon, 17-nov-2026)
- **No uses la PC de Jhon** (nada de device_stage_files / device_commit_files ni la carpeta `Desktop/JS MKG Videos`), aunque la app de escritorio esté conectada. Todo se trabaja con este repo y el chat.
- **Entradas:** Jhon adjunta en el chat las tomas numeradas (01, 02, 03a, 03b...) y, para un cliente nuevo, los videos de referencia.
- **Entrega:** el video final se envía con SendUserFile. Los videos no se guardan en el repo (pesan demasiado).
- **Al terminar cada trabajo:** commit + push de lo nuevo (estilo, plan, cambios del editor) a `main`.
- `buscar_media()` encuentra música y efectos por nombre en `/home/claude` y `/mnt/user-data/uploads`, así que los planes guardan solo el nombre del archivo.
- Solo si el repo es **privado** se pueden guardar aquí `Musica/` y `Efectos de Sonido/` (Epidemic Sound / Pixabay, licencia de Jhon). Si el repo es público, nunca los subas.

## Flujo
1. Estilo del cliente: `clientes/<cliente>/estilo.json`. Si no existe, analiza las referencias (`analizar`, `estilo`), mira las hojas de contacto y escríbelo a mano. Si las 5 referencias son muy distintas, pregunta cuál seguir.
2. `python3 -I editor.py unir tomas/*.mp4 --salida trabajo/` → ordena, se queda con la última toma repetida, quita silencios, detecta b-roll y transcribe (`trabajo/transcripcion.txt`).
3. Escribe el plan (`clientes/<cliente>/planes/<video>.json`, ver ejemplos): `correcciones`, `titulos`, `subtitulos`, `paneles`, `insertos`, `cta`, `musica` (`segmentos` para alargar canciones cortas), `impactos`, `transiciones`. Los tiempos pueden ser segundos o `{"frase": "texto dicho"}`.
4. `python3 -I editor.py editar trabajo/preparado.mp4 --transcripcion trabajo/transcripcion.json --plan PLAN --estilo clientes/<cliente>/estilo.json -o final.mp4`
5. Revisa: cuadrícula de cuadros con ffmpeg + Read, brillo con signalstats (nunca oscurecer), volumen con ebur128 (~ -14/-16 LUFS).
6. Haz commit del estilo y el plan nuevos en este repo (sin videos ni audios).

## Lo que le gusta a Jhon
- Referencia principal de SombraTek: `insta_video_95947` (tour de lujo): títulos grandes arriba en Montserrat ExtraBold que entran con desenfoque, subtítulos de una palabra, color `luminoso`, transición `whip`.
- Edición "movida" para retener: reencuadres cada ~2.4 s, golpes de zoom en títulos, sacudida + destello en títulos de `impacto`, velocidad 1.07.
- Efectos variados de su carpeta (no repetir seguido, sin pops en cada palabra). Música con energía o suspenso según pida.
- Textos inventados por Claude (títulos, CTA) se le señalan al entregar.
