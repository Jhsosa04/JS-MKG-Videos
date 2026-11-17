#!/usr/bin/env bash
# Instala todo lo que necesita editor.py (solo usa los registros de pip y npm)
set -e
cd "$(dirname "$0")"
pip install -q --break-system-packages faster-whisper fonttools brotli pillow numpy

# Modelo Whisper small (CTranslate2 int8) publicado en npm en 4 partes
if [ ! -f modelo-whisper/model.bin ]; then
  mkdir -p modelo-whisper /tmp/wm && cd /tmp/wm
  for i in 0 1 2 3; do npm pack -q @skillninja/shortmovie-telop-model-p$i >/dev/null; tar xzf skillninja-shortmovie-telop-model-p$i-*.tgz; done
  cat package/model.bin.part0 package/model.bin.part1 package/model.bin.part2 package/model.bin.part3 > package/model.bin
  echo "$(cat package/model.sha256)  package/model.bin" | sha256sum -c -
  cd - >/dev/null
  cp /tmp/wm/package/{model.bin,config.json,preprocessor_config.json,tokenizer.json,vocabulary.json} modelo-whisper/
  rm -rf /tmp/wm
fi

# Fuentes condensadas (Bebas Neue y Anton) desde npm, convertidas a TTF
if [ ! -f fonts/BebasNeue-Regular.ttf ]; then
  mkdir -p fonts /tmp/fd && cd /tmp/fd
  npm pack -q @fontsource/bebas-neue @fontsource/anton >/dev/null
  for f in *.tgz; do tar xzf "$f" --one-top-level; done
  cd - >/dev/null
  python3 -I -c "
from fontTools.ttLib import TTFont
import glob
for pat,dst in [('bebas-neue-latin-400-normal','BebasNeue-Regular.ttf'),('anton-latin-400-normal','Anton-Regular.ttf')]:
    f=TTFont(glob.glob('/tmp/fd/*/package/files/'+pat+'.woff2')[0]); f.flavor=None; f.save('fonts/'+dst)"
  rm -rf /tmp/fd
fi
python3 -I sfx.py >/dev/null
echo "Editor listo."
