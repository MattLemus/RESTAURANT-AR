#!/usr/bin/env bash
# bash splat_a_malla.sh idol.ply salida.glb [ancho_cm]
# Un plato de Idol (splat, 3D Gaussian Splatting) a malla con textura que se ve como el splat: .glb para Android y la web y
# .usdz para iPhone (salida.usdz). Un splat no se puede mostrar en AR (Quick Look ni ARCore lo leen) y en celulares sin ARCore
# trababa la GPU; la malla es liviana en cualquiera. Pasos: se dibuja el splat desde 64 vistas por arriba (color y
# profundidad), se funden las profundidades en una malla cerrada, se despliega en un mapa 4096 y se pinta con los colores de
# las vistas que ven cada punto. Unos 5 minutos con una GPU NVIDIA.
# Necesita: TORCH_PY = python con torch + CUDA (por defecto el de Idol, no se le instala nada); MALLA_PY = python con open3d,
# xatlas, trimesh, pymeshfix y scipy (un venv aparte); Blender para make_web_glb.py y glb_to_usdz.py.
set -e
D=$(cd "$(dirname "$0")" && pwd)
TORCH_PY=${TORCH_PY:-C:/Idol/.venv/Scripts/python.exe}
MALLA_PY=${MALLA_PY:-python}
BLENDER=${BLENDER:-blender}
CM=${3:-40}
TMP=$(mktemp -d)
python -I "$D/preparar.py" "$1" "$TMP/splat.ply" "$CM"
"$TORCH_PY" "$D/render_views.py" "$TMP/splat.ply" "$TMP/vistas"
"$MALLA_PY" "$D/make_mesh.py" "$TMP/vistas" "$TMP/forma.ply" 200000
"$MALLA_PY" "$D/unwrap.py" "$TMP/forma.ply" "$TMP/uv.npz" 4096
"$TORCH_PY" "$D/bake.py" "$TMP/uv.npz" "$TMP/vistas" "$TMP/textura.png"
"$MALLA_PY" "$D/exportar.py" "$TMP/uv.npz" "$TMP/textura.png" "$TMP/crudo.glb"
"$BLENDER" -b --factory-startup -P "$D/../make_web_glb.py" -- "$TMP/crudo.glb" "$2" "$CM" 0
"$BLENDER" -b --factory-startup -P "$D/../glb_to_usdz.py" -- "$2" "${2%.glb}.usdz"
rm -rf "$TMP"
