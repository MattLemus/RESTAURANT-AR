# python exportar.py uv.npz textura.png salida.glb: la malla desplegada (unwrap.py) con su textura horneada (bake.py) como glb
# sin brillo (metalico 0, rugosidad 1): la luz ya viene en los colores del splat
import sys, numpy as np, trimesh
from PIL import Image

m = np.load(sys.argv[1])
mat = trimesh.visual.material.PBRMaterial(baseColorTexture=Image.open(sys.argv[2]), metallicFactor=0.0, roughnessFactor=1.0)
t = trimesh.Trimesh(vertices=m['pos'], faces=m['faces'], vertex_normals=m['nrm'], process=False,
                    visual=trimesh.visual.TextureVisuals(uv=m['uv'], material=mat))
t.export(sys.argv[3])
print('glb', sys.argv[3], len(t.faces), 'triangulos')
