# Para make_pieces.py. Pieza detallada (foto proyectada) -> pieza liviana con sus propias texturas horneadas:
# color, relieve y brillo. Es el flujo de los modelos de Apple: malla baja + mapas de normales/rugosidad (las piezas
# "_low" del Rover, cada ingrediente de los pancakes con su juego color/normal/rugosidad).
import math
import os
import bpy
import numpy as np


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.engine = 'CYCLES'
    sc.cycles.device = 'CPU'
    sc.cycles.samples = 4
    sc.render.bake.margin = 16
    return sc


def mesh_object(name, V, F, UV=None):
    me = bpy.data.meshes.new(name)
    me.from_pydata(np.asarray(V).tolist(), [], np.asarray(F).tolist())
    me.update()
    if UV is not None:
        uvl = me.uv_layers.new(name='proj')
        UV = np.asarray(UV, np.float32)
        if len(UV) != len(me.loops):             # uv por vertice -> por esquina de cara
            lv = np.zeros(len(me.loops), int); me.loops.foreach_get('vertex_index', lv); UV = UV[lv]
        uvl.data.foreach_set('uv', UV.ravel())
    me.polygons.foreach_set('use_smooth', [True] * len(me.polygons))
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def _img(path, color=True):
    im = bpy.data.images.load(os.path.abspath(path))
    if not color:
        im.colorspace_settings.name = 'Non-Color'
    return im


def source_material(ob, color, normal, rough, normal_strength=0.5):
    """Material de la pieza detallada: lo que se hornea."""
    mat = bpy.data.materials.new(ob.name + '_src'); mat.use_nodes = True; nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED')
    out = next(n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL')
    uv = nt.nodes.new('ShaderNodeUVMap'); uv.uv_map = 'proj'
    tc = nt.nodes.new('ShaderNodeTexImage'); tc.image = _img(color)
    tn = nt.nodes.new('ShaderNodeTexImage'); tn.image = _img(normal, False)
    tr = nt.nodes.new('ShaderNodeTexImage'); tr.image = _img(rough, False)
    for t in (tc, tn, tr):
        nt.links.new(uv.outputs['UV'], t.inputs['Vector'])
    nm = nt.nodes.new('ShaderNodeNormalMap'); nm.uv_map = 'proj'; nm.inputs['Strength'].default_value = normal_strength
    nt.links.new(tn.outputs['Color'], nm.inputs['Color'])
    nt.links.new(tc.outputs['Color'], bsdf.inputs['Base Color'])
    nt.links.new(nm.outputs['Normal'], bsdf.inputs['Normal'])
    nt.links.new(tr.outputs['Color'], bsdf.inputs['Roughness'])
    em = nt.nodes.new('ShaderNodeEmission')
    ob.data.materials.append(mat)
    return dict(nt=nt, bsdf=bsdf, out=out, em=em, color=tc, rough=tr)


def make_low(name, V, F, seam_verts):
    """Malla liviana con pocas islas grandes (como las nueces de Apple): costura solo en el contorno."""
    low = mesh_object(name, V, F)
    me = low.data
    seam = np.zeros(len(me.vertices), bool); seam[np.asarray(seam_verts)] = True
    ev = np.zeros(len(me.edges) * 2, int); me.edges.foreach_get('vertices', ev); ev = ev.reshape(-1, 2)
    me.edges.foreach_set('use_seam', (seam[ev[:, 0]] & seam[ev[:, 1]]).tolist())
    me.uv_layers.new(name='UVMap')
    bpy.ops.object.select_all(action='DESELECT'); low.select_set(True)
    bpy.context.view_layer.objects.active = low
    bpy.ops.object.mode_set(mode='EDIT'); bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.unwrap(method='ANGLE_BASED', margin=0.01)
    bpy.ops.object.mode_set(mode='OBJECT')
    return low


def bake_maps(high, low, src, size, prefix, rough_default=0.5):
    """Hornea color, rugosidad y normales de high a low; deja a low con su material final (glTF/USD estandar)."""
    sc = bpy.context.scene
    name = os.path.basename(prefix)
    imgs = {k: bpy.data.images.new(f'{name}_{k}', size, size, alpha=False) for k in ('color', 'rough', 'normal')}
    imgs['rough'].colorspace_settings.name = 'Non-Color'; imgs['normal'].colorspace_settings.name = 'Non-Color'
    mat = bpy.data.materials.new(name); mat.use_nodes = True; mat.use_backface_culling = True; nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED')
    nodes = {k: nt.nodes.new('ShaderNodeTexImage') for k in imgs}
    for k, n in nodes.items():
        n.image = imgs[k]
    low.data.materials.append(mat)
    bpy.ops.object.select_all(action='DESELECT')
    high.select_set(True); low.select_set(True); bpy.context.view_layer.objects.active = low
    dims = max(high.dimensions)
    bake = sc.render.bake
    bake.use_selected_to_active = True
    bake.cage_extrusion = dims * 0.03
    bake.max_ray_distance = dims * 0.08
    snt, out = src['nt'], src['out']
    for k, socket in (('color', src['color'].outputs['Color']), ('rough', src['rough'].outputs['Color'])):
        snt.links.new(socket, src['em'].inputs['Color']); snt.links.new(src['em'].outputs['Emission'], out.inputs['Surface'])
        nt.nodes.active = nodes[k]
        bpy.ops.object.bake(type='EMIT')
    snt.links.new(src['bsdf'].outputs['BSDF'], out.inputs['Surface'])
    nt.nodes.active = nodes['normal']
    bpy.ops.object.bake(type='NORMAL', normal_space='TANGENT')
    for k, im in imgs.items():
        im.filepath_raw = os.path.abspath(f'{prefix}_{k}.png'); im.file_format = 'PNG'; im.save()
    # material final
    nt.links.new(nodes['color'].outputs['Color'], bsdf.inputs['Base Color'])
    nt.links.new(nodes['rough'].outputs['Color'], bsdf.inputs['Roughness'])
    nm = nt.nodes.new('ShaderNodeNormalMap'); nm.uv_map = 'UVMap'
    nt.links.new(nodes['normal'].outputs['Color'], nm.inputs['Color']); nt.links.new(nm.outputs['Normal'], bsdf.inputs['Normal'])
    bsdf.inputs['Metallic'].default_value = 0.0
    return low


def export_glb(ob, path):
    bpy.ops.object.select_all(action='DESELECT'); ob.select_set(True)
    loc = ob.location.copy(); ob.location = (0, 0, 0)
    bpy.ops.export_scene.gltf(filepath=path, export_format='GLB', use_selection=True, export_image_format='JPEG',
                              export_jpeg_quality=90, export_cameras=False, export_lights=False)
    ob.location = loc
