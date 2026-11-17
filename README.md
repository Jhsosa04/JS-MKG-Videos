# JS MKG · Editor de videos para clientes

Editor automático de reels 9:16: une tomas, quita silencios, transcribe, pone títulos y subtítulos animados, zooms, transiciones, corrección de color, efectos de sonido y música con ducking.

## Cómo usarlo desde cualquier equipo (laptop, iPad, otra PC)
1. Abre un chat con Claude y conecta este repositorio.
2. **Con la laptop:** escribe *"Edita el video de SombraTek"*. Claude toma las tomas de `Desktop/JS MKG Videos/` y deja el resultado en `Resultados/`.
3. **Con el iPad u otra PC:** adjunta las tomas numeradas (01, 02, 03...) en el chat y escribe *"Edita este video de SombraTek"*. Si quieres una canción o efectos específicos, adjúntalos también.

## Qué hay aquí
| Carpeta / archivo | Para qué |
|---|---|
| `editor.py` | El editor (comandos `analizar`, `estilo`, `preparar`, `unir`, `editar`) |
| `sfx.py`, `sfx/` | Efectos de sonido generados (respaldo si no hay efectos propios) |
| `fonts/` | Bebas Neue, Anton y Montserrat (licencia libre OFL) |
| `<Cliente>/Referencias, Material Grabado, Resultados, Estilo` | Igual que la carpeta JS MKG Videos de la laptop |
| `Musica/`, `Efectos de Sonido/` | Música y efectos (solo con el repo privado) |
| `estilos/` | Estilos base reutilizables |
| `CLAUDE.md` | Instrucciones de trabajo para Claude |

Los videos, la música y los efectos de Epidemic Sound **no** se guardan aquí (pesan mucho y tienen licencia). Siguen en `Desktop/JS MKG Videos/`.
