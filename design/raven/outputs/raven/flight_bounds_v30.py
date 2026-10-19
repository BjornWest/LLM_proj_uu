"""Conservative projected native silhouette bounds for route safety planning."""
import bpy

def projected_mesh_bounds(scene,camera,pad_pixels=2):
    bpy.context.view_layer.update()
    graph=bpy.context.evaluated_depsgraph_get();view=camera.matrix_world.inverted();ortho=camera.data.ortho_scale
    xs=[];ys=[]
    for obj in scene.objects:
        if obj.type!='MESH' or obj.hide_render:continue
        live=obj.evaluated_get(graph);mesh=live.to_mesh();transform=view@live.matrix_world
        for vertex in mesh.vertices:
            co=transform@vertex.co;xs.append(.5+co.x/ortho);ys.append(.5-co.y/ortho)
        live.to_mesh_clear()
    pad=pad_pixels/scene.render.resolution_x
    return {'left':min(xs)-pad,'top':min(ys)-pad,'right':max(xs)+pad,'bottom':max(ys)+pad}
