# Forma del plato a partir de las vistas del splat: fusion TSDF de las profundidades medianas (solo donde la vista es opaca),
# superficie por marching cubes, se cierra (MeshFix) y se simplifica.
import sys, glob, numpy as np, open3d as o3d, pymeshfix

vdir, out, tris = sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 300000
# volumen fijo de 42 cm de lado alrededor del plato (el escalable de Open3D 0.20 en Windows no integraba nada), ~1.1 mm por voxel
vol = o3d.pipelines.integration.UniformTSDFVolume(length=0.42, resolution=384, sdf_trunc=0.005,
                                                   color_type=o3d.pipelines.integration.TSDFVolumeColorType.NoColor,
                                                   origin=np.array([[-0.21], [-0.01], [-0.21]]))
for p in sorted(glob.glob(f'{vdir}/v*.npz')):
    v = np.load(p)
    W, H, f = int(v['W']), int(v['H']), float(v['f'])
    d = np.where(v['a'] > 160, v['d'], 0).astype(np.float32)
    rgbd = o3d.geometry.RGBDImage.create_from_color_and_depth(o3d.geometry.Image(np.ascontiguousarray(v['rgb'])), o3d.geometry.Image(d),
                                                              depth_scale=1.0, depth_trunc=3.0, convert_rgb_to_intensity=False)
    E = np.eye(4); E[:3, :3] = v['R']; E[:3, 3] = v['t']
    vol.integrate(rgbd, o3d.camera.PinholeCameraIntrinsic(W, H, f, f, W / 2 - 0.5, H / 2 - 0.5), E)
m = vol.extract_triangle_mesh()
print('crudo', len(m.triangles))
# Ninguna vista ve el fondo (el plato esta en la mesa) ni lo que queda bajo camarones y conchas: ahi la malla quedaba abierta
# y se veia a traves. MeshFix tapa esos huecos y deja solo la pieza principal (fuera motas y trozos flotantes del splat,
# como la cebolla suelta sobre el ceviche de la bandeja)
fix = pymeshfix.MeshFix(np.asarray(m.vertices), np.asarray(m.triangles))
fix.repair(joincomp=False, remove_smallest_components=True)
m = o3d.geometry.TriangleMesh(o3d.utility.Vector3dVector(fix.points), o3d.utility.Vector3iVector(fix.faces))
m = m.simplify_quadric_decimation(tris)
m.remove_degenerate_triangles(); m.remove_unreferenced_vertices(); m.compute_vertex_normals()
print('final', len(m.triangles), 'caja', np.asarray(m.vertices).min(0).round(3), np.asarray(m.vertices).max(0).round(3))
o3d.io.write_triangle_mesh(out, m)
