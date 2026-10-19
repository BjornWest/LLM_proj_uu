"""Extract accepted saved Blender poses for the isolated live WebGL prototype.

Run Blender --background --python work/export_raven_live_v34.py.
This reads the native scenes, evaluates meshes, and writes new JSON/binary data.
It never builds, saves, changes, or renders the original scenes on disk.
"""
import argparse, array, hashlib, json, math, struct, sys, time
from pathlib import Path
import bpy
from mathutils import Matrix, Vector
from bpy_extras.object_utils import world_to_camera_view

ROOT = Path(__file__).resolve().parent.parent
P = ROOT / 'outputs' / 'raven'
WORK = ROOT / 'work'
parser = argparse.ArgumentParser()
parser.add_argument('--scout', action='store_true')
parser.add_argument('--fps', type=int, default=15)
args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])
DEST = WORK / 'live-v34-scout' if args.scout else P
DEST.mkdir(parents=True, exist_ok=True)
JSON_PATH = DEST / 'live-raven-v34.json'
BIN_PATH = DEST / 'live-raven-v34.bin'
SOURCES = [
    ('perch26', 'raven-chat-perch-v26.blend', 'chat-perch-v26.json', ['pet', 'caw']),
    ('idle29', 'raven-chat-idle-v29.blend', 'chat-idle-native-v29.json', ['perch', 'idle']),
    ('flight26', 'raven-chat-flight-v26.blend', 'chat-flight-v26.json', ['takeoff', 'glide_right', 'glide', 'diving']),
    ('flight30', 'raven-flight-modules-v30.blend', 'flight-modules-v30.json', None),
    ('attention24', 'raven-chat-attention-v24.blend', 'chat-attention.json', ['attention']),
]

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

protected = {name: sha(P / name) for _, blend, meta, _ in SOURCES for name in [blend, meta]}
data = {
    'version': 34, 'format': 'raven-evaluated-local-poses-1',
    'coordinateSystem': 'Blender Z-up; native camera looks along its local -Z, with local +Y up',
    'colorSpace': 'linear scene RGB, direct native emission colors; no tone mapping',
    'binary': {'uri': BIN_PATH.name, 'endianness': 'little'},
    'arrays': [], 'geometries': [], 'rigs': {}, 'clips': {},
    'interpolation': {'geometry': 'linear local vertex coordinates', 'positionScale': 'linear',
                      'rotation': 'shortest quaternion slerp', 'nativeTransformStride': 10,
                      'nativeTransformOrder': ['positionXYZ', 'quaternionXYZW', 'scaleXYZ']},
    'sourceProtection': protected,
}
binary = bytearray()
array_bank = {}
geometry_bank = {}
report = {'sources': {}, 'samples': 0, 'meshesEvaluated': 0, 'maxLocalTrsError': 0,
          'maxWorldTrsError': 0, 'maxSourceAnchorProjectionError': 0,
          'maxPackedAnchorProjectionError': 0, 'curveObjects': [], 'topologyChecks': 0,
          'readonlySourcesBefore': protected, 'clipCounts': {}}
started = time.perf_counter()

def add_array(values, item_size, type_name='Float32'):
    raw = array.array('f' if type_name == 'Float32' else 'H', values)
    if sys.byteorder != 'little': raw.byteswap()
    blob = raw.tobytes()
    key = (type_name, item_size, hashlib.sha256(blob).hexdigest())
    if key in array_bank: return array_bank[key]
    while len(binary) % 4: binary.append(0)
    index = len(data['arrays'])
    data['arrays'].append({'byteOffset': len(binary), 'count': len(raw), 'itemSize': item_size, 'type': type_name})
    binary.extend(blob); array_bank[key] = index
    return index

def add_geometry(values):
    ref = add_array(values, 3)
    if ref not in geometry_bank:
        geometry_bank[ref] = len(data['geometries'])
        data['geometries'].append({'positions': ref, 'vertexCount': len(values) // 3})
    return geometry_bank[ref]

def color(material):
    if material is None: return [1., 1., 1., 1.]
    if material.use_nodes and material.node_tree:
        for node in material.node_tree.nodes:
            if node.type == 'EMISSION': return list(node.inputs['Color'].default_value)
        for node in material.node_tree.nodes:
            if node.type == 'BSDF_PRINCIPLED': return list(node.inputs['Base Color'].default_value)
    return list(material.diffuse_color)

def layout(mesh, obj):
    mesh.calc_loop_triangles()
    triangles, rgb, alpha = [], [], []
    for triangle in mesh.loop_triangles:
        face = mesh.polygons[triangle.polygon_index]
        material = obj.data.materials[face.material_index] if face.material_index < len(obj.data.materials) else None
        rgba = color(material)
        for vertex in triangle.vertices:
            triangles.append(vertex); rgb.extend(rgba[:3]); alpha.append(rgba[3])
    signature = tuple((tuple(face.vertices), face.material_index) for face in mesh.polygons)
    return triangles, rgb, alpha, signature

def frames_for(item, name):
    count = item['frames']
    if name == 'attention': return list(range(count)) if not args.scout else [0, 112, 224, 225, 337, 449]
    if args.scout: return sorted(set([0, min(3, count - 1), count // 2, max(0, count - 4), count - 1]))
    fps = item.get('fps', 60)
    step = max(1, round(fps / args.fps))
    chosen = set(range(0, count, step)) | {0, count - 1}
    for edge in range(min(4, count)):
        chosen.add(edge); chosen.add(count - 1 - edge)
    poses = item.get('poses', [])
    # Short blinks and rapid idle turns retain all native movement samples.
    for index, pose in enumerate(poses):
        if pose.get('eyeClosure', 0) > .001:
            chosen.update(range(max(0, index - 1), min(count, index + 2)))
        if name == 'idle' and index and pose.get('headTilt') != poses[index - 1].get('headTilt'):
            chosen.update([index - 1, index])
    # Important push-off release/contact frames and canonical bridge holds.
    if name == 'takeoff': chosen.update([37, 38, 39, 40])
    if name == 'diving': chosen.update([167, 168, 169, 234])
    return sorted(f for f in chosen if 0 <= f < count)

def project(scene, camera, point):
    value = world_to_camera_view(scene, camera, point)
    return {'x': float(value.x), 'y': 1 - float(value.y)}

def lift_anchor(camera, point, depth):
    # Orthographic unprojection, retaining exact legacy virtual contact markers.
    local = Vector(((point['x'] - .5 - camera.data.shift_x) * camera.data.ortho_scale,
                    (.5 - point['y'] - camera.data.shift_y) * camera.data.ortho_scale, -depth))
    return camera.matrix_world @ local

def world_anchors(scene, pose, rig_id):
    objects = scene.objects
    root = objects.get('Raven • whole character')
    head = objects.get('Head • tilt and attention')
    upper = objects.get('Upper beak • caw')
    feet = [obj for obj in objects if obj.name.startswith('Foot ') and obj.type == 'EMPTY']
    points = {}
    if root:
        points['root'] = Vector((0, 0, 1.3)) if rig_id.startswith('flight') else root.matrix_world.translation.copy()
    if head: points['head'] = head.matrix_world @ Vector((.11, 0, .22))
    if upper:
        opening = pose.get('cawOpen', 0)
        points['beak'] = upper.matrix_world @ Vector(((464 - 397) / 140, 0, (-14 + 44 * opening) / 140))
    if feet: points['foot'] = sum((obj.matrix_world @ Vector((.08, 0, -.07)) for obj in feet), Vector()) / len(feet)
    camera = scene.camera
    depth = -(camera.matrix_world.inverted() @ points.get('root', Vector((0, 0, 1.3)))).z
    for name in ['root', 'head', 'beak', 'foot', 'contact']:
        if name not in pose or not isinstance(pose[name], dict): continue
        if name == 'contact' and pose.get('groundContactWorld'):
            points[name] = Vector(pose['groundContactWorld'])
        elif name not in points:
            points[name] = lift_anchor(camera, pose[name], depth)
        projected = project(scene, camera, points[name])
        error = max(abs(projected[axis] - pose[name][axis]) for axis in ['x', 'y'])
        report['maxSourceAnchorProjectionError'] = max(report['maxSourceAnchorProjectionError'], error)
        if error > 2e-6:
            # Certain legacy markers deliberately differ from the moving object
            # pivot. Preserve that actual published projection as the authority.
            points[name] = lift_anchor(camera, pose[name], depth)
        final = project(scene, camera, points[name])
        report['maxPackedAnchorProjectionError'] = max(report['maxPackedAnchorProjectionError'], max(abs(final[a]-pose[name][a]) for a in ['x','y']))
    return {name: list(point) for name, point in points.items()}

for rig_id, blend_name, metadata_name, selection in SOURCES:
    bpy.ops.wm.open_mainfile(filepath=str(P / blend_name))
    scene = bpy.context.scene
    metadata = json.loads((P / metadata_name).read_text(encoding='utf-8'))
    source_clips = metadata.get('clips', {})
    if rig_id == 'attention24':
        source_clips = {'attention': {'frames': metadata['frames'], 'fps': metadata['fps'], 'duration': 0,
                                    'startFrame': 1, 'loop': False, 'poses': metadata['poses']}}
        data['attention'] = {key: metadata[key] for key in ['yaw', 'pitch', 'tilt', 'blinkLayers', 'order']}
        data['attention'].update(clip='attention', interpolation='multilinear over yaw/pitch/tilt/blink grid; quaternion hemisphere corrected pairwise')
    renderable_types = {'MESH', 'CURVE', 'SURFACE', 'FONT', 'META'}
    meshes = sorted([obj for obj in scene.objects if obj.type in renderable_types and not obj.hide_render], key=lambda obj: obj.name)
    wanted = set(meshes)
    for obj in meshes:
        ancestor = obj.parent
        while ancestor: wanted.add(ancestor); ancestor = ancestor.parent
    def depth(obj):
        return 0 if obj.parent is None else depth(obj.parent) + 1
    nodes = sorted(wanted, key=lambda obj: (depth(obj), obj.name))
    node_index = {obj.name: index for index, obj in enumerate(nodes)}
    rig = {'sourceBlend': blend_name, 'sourceMetadata': metadata_name,
           'nodes': [{'name': obj.name, 'parent': node_index.get(obj.parent.name) if obj.parent else None, 'type': obj.type} for obj in nodes],
           'meshes': [], 'camera': {'aspect': 1, 'nominalWidth': metadata.get('frameWidth', 512), 'nominalHeight': metadata.get('frameHeight', 512)},
           'view': {'transform': scene.view_settings.view_transform, 'look': scene.view_settings.look,
                    'exposure': scene.view_settings.exposure, 'gamma': scene.view_settings.gamma},
           'rootNode': node_index.get('Raven • whole character'), 'headNode': node_index.get('Head • tilt and attention')}
    data['rigs'][rig_id] = rig
    first_clip = source_clips[(selection or list(source_clips))[0]]
    scene.frame_set(first_clip['startFrame']); graph = bpy.context.evaluated_depsgraph_get()
    signatures = {}
    for obj in meshes:
        ev = obj.evaluated_get(graph); mesh = ev.to_mesh()
        try:
            indices, rgb, alpha, signature = layout(mesh, obj)
            signatures[obj.name] = signature
            rig['meshes'].append({'name': obj.name, 'node': node_index[obj.name], 'vertexCount': len(mesh.vertices),
                                  'triangles': add_array(indices, 1, 'Uint16'), 'colors': add_array(rgb, 3),
                                  'alpha': add_array(alpha, 1), 'trianglesCount': len(indices) // 3,
                                  'doubleSided': True, 'convertedFrom': obj.type})
        finally: ev.to_mesh_clear()
        if obj.type != 'MESH': report['curveObjects'].append({'rig': rig_id, 'name': obj.name, 'type': obj.type})
    rig['statistics'] = {'nodes': len(nodes), 'meshObjects': len(meshes),
                         'vertices': sum(mesh['vertexCount'] for mesh in rig['meshes']),
                         'triangles': sum(mesh['trianglesCount'] for mesh in rig['meshes'])}
    report['sources'][rig_id] = rig['statistics']
    for clip_name in (selection or list(source_clips)):
        item = source_clips[clip_name]; chosen = frames_for(item, clip_name)
        source_fps = item.get('fps', metadata.get('fps', 60))
        clip = {key: item[key] for key in ['frames', 'fps', 'duration', 'loop', 'action', 'startHeading', 'endHeading', 'startJunction', 'endJunction', 'displacement', 'endpointVelocity'] if key in item}
        clip.update(rig=rig_id, fps=source_fps, duration=item.get('duration', item['frames'] / source_fps),
                    nativeStartFrame=item['startFrame'], samples=[],
                    poseBank={'sourceFrames': item['frames'], 'nativeFps': source_fps,
                              'samplingFps': args.fps if clip_name != 'attention' else None, 'frameIndices': chosen,
                              'kind': 'all exact grid poses' if clip_name == 'attention' else '15fps native evaluation plus exact junction, blink and rapid-turn samples'})
        data['clips'][clip_name] = clip
        previous_quaternions = {}
        camera_previous = None
        for frame in chosen:
            scene.frame_set(item['startFrame'] + frame); bpy.context.view_layer.update()
            graph = bpy.context.evaluated_depsgraph_get()
            transforms = []
            for index, obj in enumerate(nodes):
                ev = obj.evaluated_get(graph); world = ev.matrix_world
                parent_world = obj.parent.evaluated_get(graph).matrix_world if obj.parent else Matrix.Identity(4)
                local = parent_world.inverted_safe() @ world
                position, quaternion, scale = local.decompose()
                if index in previous_quaternions and quaternion.dot(previous_quaternions[index]) < 0: quaternion.negate()
                previous_quaternions[index] = quaternion.copy()
                rebuilt = Matrix.LocRotScale(position, quaternion, scale)
                local_error = max(abs(local[row][col] - rebuilt[row][col]) for row in range(4) for col in range(4))
                world_rebuilt = parent_world @ rebuilt
                world_error = max(abs(world[row][col] - world_rebuilt[row][col]) for row in range(4) for col in range(4))
                report['maxLocalTrsError'] = max(report['maxLocalTrsError'], local_error)
                report['maxWorldTrsError'] = max(report['maxWorldTrsError'], world_error)
                assert local_error < 3e-5 and world_error < 5e-5, ('Non-TRS local requires matrix export', rig_id, clip_name, frame, obj.name, local_error, world_error)
                transforms.extend([*position, quaternion.x, quaternion.y, quaternion.z, quaternion.w, *scale])
            geometry = []
            for obj, mesh_spec in zip(meshes, rig['meshes']):
                ev = obj.evaluated_get(graph); mesh = ev.to_mesh()
                try:
                    signature = tuple((tuple(face.vertices), face.material_index) for face in mesh.polygons)
                    assert len(mesh.vertices) == mesh_spec['vertexCount'] and signature == signatures[obj.name], ('Changing topology', rig_id, clip_name, frame, obj.name)
                    coords = [coordinate for vertex in mesh.vertices for coordinate in vertex.co]
                    geometry.append(add_geometry(coords)); report['meshesEvaluated'] += 1; report['topologyChecks'] += 1
                finally: ev.to_mesh_clear()
            camera = scene.camera; cp, cq, cs = camera.matrix_world.decompose()
            if camera_previous is not None and cq.dot(camera_previous) < 0: cq.negate()
            camera_previous = cq.copy()
            pose = item.get('poses', [{}])[frame]
            sample = {'frame': frame, 'time': frame / source_fps, 'geometry': geometry,
                      'transforms': add_array(transforms, 10), 'visible': [not obj.hide_render for obj in nodes],
                      'camera': {'position': list(cp), 'quaternion': [cq.x, cq.y, cq.z, cq.w],
                                 'orthoScale': camera.data.ortho_scale, 'near': camera.data.clip_start, 'far': camera.data.clip_end,
                                 'shiftX': camera.data.shift_x, 'shiftY': camera.data.shift_y, 'aspect': 1},
                      'pose': pose, 'worldAnchors': world_anchors(scene, pose, rig_id),
                      'worldAnchorKind': 'native root/head/beak/foot markers; published virtual contact/legacy marker lifted when needed for exact orthographic projection'}
            clip['samples'].append(sample); report['samples'] += 1
        report['clipCounts'][clip_name] = len(chosen)
        print('LIVE_V34_EXTRACTED', rig_id, clip_name, len(chosen), 'samples', len(binary), 'binary bytes', flush=True)

# Six logical backwards-wind banks intentionally share physical soar geometry.
for heading in ['r', 'ra', 'rt', 'l', 'la', 'lt']:
    source = 'steady_' + heading
    item = data['clips'][source]
    data['clips']['wind_' + heading] = {key: value for key, value in item.items() if key not in ['samples', 'poseBank']}
    data['clips']['wind_' + heading].update(aliasOf=source, action='soar_backward')

after = {name: sha(P / name) for name in protected}
assert protected == after, 'Original source files changed during read-only extraction'
BIN_PATH.write_bytes(binary)
data['binary'].update(byteLength=len(binary), sha256=sha(BIN_PATH))
data['sampling'] = {'nativeEvaluatedSamples': report['samples'], 'geometrySampleFps': args.fps,
                    'continuousBrowserInterpolation': True, 'noRasterFrames': True,
                    'noArmatureOrShapeKeyBankTransferred': True, 'scout': args.scout}
JSON_PATH.write_text(json.dumps(data, separators=(',', ':'), ensure_ascii=False), encoding='utf-8')
report.update(readonlySourcesAfter=after, originalSourcesUnchanged=True, binaryBytes=len(binary),
              binarySha256=sha(BIN_PATH), jsonBytes=JSON_PATH.stat().st_size, jsonSha256=sha(JSON_PATH),
              uniqueArrays=len(data['arrays']), uniqueLocalGeometry=len(data['geometries']),
              seconds=time.perf_counter()-started, outputJson=str(JSON_PATH), outputBin=str(BIN_PATH),
              clips=len(data['clips']), rigs=len(data['rigs']), allTopologyConstant=True)
report_path = WORK / ('live-raven-v34-scout-extraction-report.json' if args.scout else 'live-raven-v34-extraction-report.json')
report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
print('LIVE_V34_COMPLETE', json.dumps({key: report[key] for key in ['samples','binaryBytes','jsonBytes','uniqueLocalGeometry','seconds','maxLocalTrsError','maxWorldTrsError','maxPackedAnchorProjectionError']}), flush=True)
