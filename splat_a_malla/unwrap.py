# Despliega la malla en un mapa UV (xatlas) para pintarle una textura de RES x RES; guarda posiciones, normales, caras y uv.
import sys, time, numpy as np, open3d as o3d, xatlas

src, out, res = sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 4096
m = o3d.io.read_triangle_mesh(src); m.compute_vertex_normals()
V, F, N = np.asarray(m.vertices, np.float32), np.asarray(m.triangles, np.uint32), np.asarray(m.vertex_normals, np.float32)
t0 = time.time()
atlas = xatlas.Atlas(); atlas.add_mesh(V, F, N)
po = xatlas.PackOptions(); po.resolution = res; po.padding = 4; po.bilinear = True
atlas.generate(xatlas.ChartOptions(), po)
vmap, idx, uv = atlas[0]
print('cartas', atlas.chart_count, 'uso', round(atlas.utilization, 3), 'segundos', round(time.time() - t0))
np.savez(out, pos=V[vmap], nrm=N[vmap], faces=idx.astype(np.int64), uv=uv.astype(np.float32), res=res)
