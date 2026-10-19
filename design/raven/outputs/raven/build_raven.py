"""Build the editable raven and render sprites. Run with Blender --background --python this_file."""
import bpy, math, random, sys, json
from pathlib import Path
from mathutils import Vector, Matrix
from mathutils.bvhtree import BVHTree
from mathutils.geometry import delaunay_2d_cdt

OUT = Path(__file__).resolve().parent
FRAMES = OUT / 'frames'
FRAMES.mkdir(parents=True, exist_ok=True)
random.seed(24)
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
scene = bpy.context.scene

def mat(name, color, roughness=.8):
    m=bpy.data.materials.new(name)
    m.diffuse_color=(*color,1)
    m.use_nodes=True
    bs=m.node_tree.nodes.get('Principled BSDF')
    bs.inputs['Base Color'].default_value=(*color,1)
    bs.inputs['Roughness'].default_value=roughness
    return m

def flat_color(m,rgb):
    m['palette_base_srgb']=list(rgb)
    color=tuple(v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4 for v in rgb)
    m.diffuse_color=(*color,1)
    nodes=m.node_tree.nodes;nodes.clear()
    output=nodes.new('ShaderNodeOutputMaterial');emission=nodes.new('ShaderNodeEmission')
    emission.inputs['Color'].default_value=(*color,1)
    emission.inputs['Strength'].default_value=1
    m.node_tree.links.new(emission.outputs[0],output.inputs['Surface'])

def set_palette(darker=False):
    factor=.82 if darker else 1
    for m in bpy.data.materials:
        if 'palette_base_srgb' not in m:continue
        rgb=[v*factor for v in m['palette_base_srgb']]
        linear=tuple(v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4 for v in rgb)
        m.diffuse_color=(*linear,1)
        for node in m.node_tree.nodes:
            if node.type=='EMISSION':node.inputs['Color'].default_value=(*linear,1)
    scene['Palette']='Darker charcoal' if darker else 'Current charcoal'


charcoal=[mat('Charcoal facet %02d'%i,(.009+i*.0024,.012+i*.0026,.018+i*.0032)) for i in range(8)]
wingm=[mat('Wing plane %02d'%i,(.010+i*.0033,.014+i*.0035,.021+i*.0040)) for i in range(8)]
beakm=[mat('Beak facet %02d'%i,(.018+i*.004,.022+i*.004,.029+i*.005)) for i in range(5)]
feetm=[mat('Feet facet %02d'%i,(.016+i*.003,.019+i*.003,.025+i*.003)) for i in range(5)]
eye=mat('Pale silver eyes',(.80,.84,.85),.85)
black=mat('Eye socket',(.008,.01,.014))
mouth=mat('Mouth interior • black',(.015,.018,.023))
flat_color(mouth,(.015,.018,.023))
flat_color(eye,(.80,.82,.83))
flat_color(black,(.045,.05,.06))
for i,m in enumerate(beakm):flat_color(m,(.12+i*.032,.13+i*.032,.15+i*.035))
for i,m in enumerate(feetm):flat_color(m,(.10+i*.014,.11+i*.014,.13+i*.014))
for i,m in enumerate(charcoal):flat_color(m,(.08+i*.012,.09+i*.012,.11+i*.012))

def empty(name, loc, parent=None):
    o=bpy.data.objects.new(name,None); scene.collection.objects.link(o)
    o.location=loc; o.empty_display_type='PLAIN_AXES'; o.empty_display_size=.16
    if parent: o.parent=parent
    return o

def shade(o,mats):
    for m in mats:o.data.materials.append(m)
    for p in o.data.polygons:p.material_index=random.randrange(len(mats));p.use_smooth=False
    return o

def ico(name,loc,scale,mats=charcoal,parent=None,sub=2):
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=sub,radius=1,location=(0,0,0))
    o=bpy.context.object;o.name=name;o.location=loc;o.scale=scale
    if parent:o.parent=parent
    shade(o,mats)
    return o

def mesh(name,verts,faces,mats=charcoal,parent=None):
    me=bpy.data.meshes.new(name);me.from_pydata(verts,[],faces);me.update()
    o=bpy.data.objects.new(name,me);scene.collection.objects.link(o)
    if parent:o.parent=parent
    shade(o,mats);return o

def feather(name,root,tip,width,thickness,parent):
    a=Vector(root);b=Vector(tip);d=b-a
    # Thin diamond cross section; raised central ridge makes large graphic facets.
    transverse=Vector((d.z,0,-d.x)).normalized()*width
    mid=a+d*.48; upper=a+d*.15
    v=[a-transverse*.35,a+transverse*.35,upper+transverse*.82,mid+transverse,
       b,mid-transverse,upper-transverse*.82,mid+Vector((0,thickness,0)),
       mid-Vector((0,thickness,0))]
    faces=[(0,1,7),(1,2,7),(2,3,7),(3,4,7),(4,5,7),(5,6,7),(6,0,7),
           (1,0,8),(2,1,8),(3,2,8),(4,3,8),(5,4,8),(6,5,8),(0,6,8)]
    return mesh(name,[tuple(x) for x in v],faces,parent=parent)

def rod(name,a,b,r1,r2,parent,mats=feetm):
    va=Vector(a);vb=Vector(b);d=vb-va
    bpy.ops.mesh.primitive_cone_add(vertices=5,radius1=r1,radius2=r2,depth=d.length)
    o=bpy.context.object;o.name=name;o.parent=parent;o.location=(va+vb)/2
    o.rotation_euler=d.to_track_quat('Z','Y').to_euler();shade(o,mats);return o

def loft(name,rings,parent,segments=10):
    verts=[]
    for z,cx,rx,ry,phase in rings:
        for j in range(segments):
            angle=math.tau*j/segments+phase
            verts.append((cx+rx*math.cos(angle),ry*math.sin(angle),z))
    faces=[]
    for k in range(len(rings)-1):
        for j in range(segments):
            a=k*segments+j;b=k*segments+(j+1)%segments
            c=(k+1)*segments+(j+1)%segments;d=(k+1)*segments+j
            faces.extend([(a,b,c),(a,c,d)] if (j+k)%2 else [(a,b,d),(b,c,d)])
    faces.append(tuple(reversed(range(segments))))
    faces.append(tuple(range((len(rings)-1)*segments,len(rings)*segments)))
    return mesh(name,verts,faces,parent=parent)

def panel(name,outline,interior,position,parent,side=-1,mats=charcoal):
    points=[Vector(p) for p in outline+interior]
    coords,edges,faces,*rest=delaunay_2d_cdt(points,[],[list(range(len(outline)))],1,1e-6)
    return mesh(name,[position(p.x,p.y) for p in coords],
                [tuple(f if side==-1 else reversed(f)) for f in faces],mats,parent=parent)

def silhouette_body(outline,interior,parent,name='Continuous breast, neck and angular head',z_offset=1.42,boundary_depths=None):
    # A deliberately drawn side contour and irregular broad facets, rather than
    # spherical primitives or evenly spaced latitude rings.
    points=[Vector(p) for p in outline]+[Vector((x,z)) for x,z,depth in interior]
    coords,edges,faces,*rest=delaunay_2d_cdt(points,[],[list(range(len(outline)))],1,1e-6)
    verts=[];indices={}
    for i,p in enumerate(coords):
        source=min(range(len(points)),key=lambda j:(points[j]-p).length_squared)
        depth=(boundary_depths[source] if boundary_depths else 0) if source<len(outline) else interior[source-len(outline)][2]
        if depth==0:
            indices[i,-1]=indices[i,1]=len(verts);verts.append((p.x,0,p.y-z_offset))
        else:
            for side in [-1,1]:
                indices[i,side]=len(verts);verts.append((p.x,side*depth,p.y-z_offset))
    tris=[]
    for side in [-1,1]:
        for f in faces:
            tris.append(tuple(indices[i,side] for i in (f if side==-1 else reversed(f))))
    # Finite-width contour points need a front rim, so a muzzle or bill root
    # has a closed cross-section rather than two surfaces meeting on a pin.
    border=[min(range(len(coords)),key=lambda j:(coords[j]-p).length_squared) for p in points[:len(outline)]]
    signed_area=sum(a.x*b.y-b.x*a.y for a,b in zip(points[:len(outline)],points[1:len(outline)]+points[:1]))
    for a,b in zip(border,border[1:]+border[:1]):
        quad=(indices[a,-1],indices[a,1],indices[b,1],indices[b,-1])
        for triangle in [(quad[0],quad[1],quad[2]),(quad[0],quad[2],quad[3])]:
            if len(set(triangle))==3:tris.append(triangle if signed_area>0 else tuple(reversed(triangle)))
    return mesh(name,verts,tris,parent=parent)

def folded_wing_volume(name,outline,interior,parent,side):
    points=[Vector(p) for p in outline+interior]
    coords,edges,faces,*rest=delaunay_2d_cdt(points,[],[list(range(len(outline)))],1,1e-6)
    used=sorted({i for f in faces for i in f})
    remap={i:j for j,i in enumerate(used)}
    coords=[coords[i] for i in used]
    faces=[tuple(remap[i] for i in f) for f in faces]
    verts=[]
    for inner in [False,True]:
        for p in coords:
            bulk=math.exp(-((p.x+.48)/.72)**2-((p.y+.36)/.70)**2)
            rise=max(0,min(1,(-p.y-.01)/.30))
            bulk*=rise*rise*(3-2*rise)
            depth=(-.015-.12*bulk) if inner else (.005+.30*bulk)
            # The shoulder sits farther aft on the slimmer body. Keep the
            # distal folded feather tips in their approved positions while
            # drawing the root behind the exposed neck.
            distal=max(0,min(1,(-p.x-.25)/1.0));distal=distal*distal*(3-2*distal)
            verts.append((p.x+.118*distal,side*depth,p.y+.213*distal))
    count=len(coords);tris=[];boundary={}
    for face in faces:
        front=tuple(face if side==-1 else reversed(face))
        tris.extend([front,tuple(i+count for i in reversed(front))])
        for a,b in zip(front,front[1:]+front[:1]):
            edge=tuple(sorted((a,b)))
            boundary.setdefault(edge,[]).append((a,b))
    for occurrences in boundary.values():
        if len(occurrences)==1:
            a,b=occurrences[0]
            tris.extend([(a,b+count,b),(a,a+count,b+count)])
    wing=mesh(name,verts,tris,wingm,parent)
    wing.shape_key_add(name='Basis')
    spread=wing.shape_key_add(name='Flight spread')
    # Unfold the same closed wing into a broad, fingered flight outline.
    # The folded neutral mesh is preserved at a zero shape-key value.
    flight_outline=[(-.12,-.64),(-.10,.25),(.70,.75),(1.55,.60),
                    (2.00,.36),(2.60,.34),(2.12,.18),(2.83,.04),
                    (2.17,-.17),(2.62,-.41),(1.60,-.76),(.80,-.67),(-.11,-.82)]
    anchors={min(range(count),key=lambda i:(coords[i]-Vector(p)).length_squared):Vector(q)
             for p,q in zip(outline,flight_outline)}
    # The concave groove between the two longest primaries needs its own
    # interior guide; a uniform average would put that facet across the groove.
    groove=min(range(count),key=lambda i:(coords[i]-Vector((-1.40,-1.1642857))).length_squared)
    anchors[groove]=Vector((2.00,-.20))
    inner_groove=min(range(count),key=lambda i:(coords[i]-Vector((-1.2285714,-1.0857143))).length_squared)
    anchors[inner_groove]=Vector((1.90,-.30))
    neighbors={i:set() for i in range(count)}
    for face in faces:
        for a,b in zip(face,face[1:]+face[:1]):neighbors[a].add(b);neighbors[b].add(a)
    positions={i:anchors.get(i,Vector((1.2,-.10))).copy() for i in range(count)}
    for iteration in range(400):
        positions={i:anchors[i].copy() if i in anchors else
                   sum((positions[j] for j in neighbors[i]),Vector((0,0)))/len(neighbors[i])
                   for i in range(count)}
    def area(a,b,c):return (b.x-a.x)*(c.y-a.y)-(b.y-a.y)*(c.x-a.x)
    # Keep the existing facet topology while opening a concave feather fan.
    # Project free interior points until every triangle keeps its winding.
    for iteration in range(400):
        corrections=0
        for face in faces:
            a,b,c=(positions[i] for i in face)
            signed=area(a,b,c)
            if signed<-.0001:continue
            gradients=[Vector((b.y-c.y,c.x-b.x)),Vector((c.y-a.y,a.x-c.x)),Vector((a.y-b.y,b.x-a.x))]
            norm=sum(g.length_squared for i,g in zip(face,gradients) if i not in anchors)
            if norm==0:continue
            for i,g in zip(face,gradients):
                if i not in anchors:positions[i]-=g*((signed+.0002)/norm)
            corrections+=1
        if not corrections:break
    inverted=sum(area(coords[f[0]],coords[f[1]],coords[f[2]])*
                 area(positions[f[0]],positions[f[1]],positions[f[2]])<0 for f in faces)
    assert inverted==len(faces), (name,'flight surface folds over itself',inverted,len(faces),[f for f in faces if area(positions[f[0]],positions[f[1]],positions[f[2]])>0])
    for i,point in positions.items():
        span,chord=point
        chord-=.22*max(0,span)
        thickness=.018+.050*math.exp(-span/.80)
        spread.data[i].co=(-thickness,side*span,chord)
        spread.data[i+count].co=(thickness,side*span,chord)
    flex=wing.shape_key_add(name='Feather flex')
    flex.slider_min=-1;flex.slider_max=1
    for i,point in positions.items():
        span,chord=point
        chord-=.22*max(0,span)
        outer=max(0,min(1,(span-.7)/2.13));outer=outer*outer*(3-2*outer)
        # Bend the primary feathers behind the wrist, with a little fan opening.
        delta=Vector((-.19*outer,side*.045*outer,.065*outer*(chord+.15)))
        flex.data[i].co=Vector(verts[i])+delta
        flex.data[i+count].co=Vector(verts[i+count])+delta
    tuck=wing.shape_key_add(name='Roll elbow tuck')
    for i,point in positions.items():
        span,chord=point
        # Sweep the wrist and primaries aft and draw them inward. This is
        # additive to Flight spread, so the perched mesh remains identical.
        outer=max(0,min(1,(span-.45)/2.38));outer=outer*outer*(3-2*outer)
        delta=Vector((0,-side*.60*outer,-.56*outer))
        tuck.data[i].co=Vector(verts[i])+delta
        tuck.data[i+count].co=Vector(verts[i+count])+delta
    return wing

def from_reference(px,py):
    return ((px-300)/140,(510-py)/140)

def reference_outline(points,origin=(0,0)):
    return [(from_reference(x,y)[0]-origin[0],from_reference(x,y)[1]-origin[1]) for x,y in points]

def reference_interior(points,origin=(0,0)):
    return [(from_reference(x,y)[0]-origin[0],from_reference(x,y)[1]-origin[1],depth) for x,y,depth in points]

reference_image=bpy.data.images.load(str(OUT/'reference-perched.png'),check_existing=True)
reference_pixels=list(reference_image.pixels)
reference_width,reference_height=reference_image.size
def sampled_facet_colors(obj,origin=(0,1.42)):
    materials={}
    for face in obj.data.polygons:
        points=[obj.data.vertices[i].co for i in face.vertices]
        projected=sorted({(round(p.x,7),round(p.z,7)) for p in points})
        # A rim quad is two triangles across the centre line. Sample its
        # shared projected edge once, so both halves have identical colour.
        p=Vector((sum(p[0] for p in projected)/len(projected),0,
                  sum(p[1] for p in projected)/len(projected)))
        px=round((p.x+origin[0])*140+300)-45
        py=round(510-(p.z+origin[1])*140)-125
        samples=[]
        for dx in [-3,0,3]:
            for dy in [-3,0,3]:
                x=max(0,min(reference_width-1,px+dx));y=max(0,min(reference_height-1,py+dy))
                offset=((reference_height-1-y)*reference_width+x)*4
                samples.append(tuple(reference_pixels[offset:offset+3]))
        rgb=tuple(sorted(v[channel] for v in samples)[4] for channel in range(3))
        # Ignore a sampled white background at very thin feather edges.
        if min(rgb)>.6:rgb=(.10,.115,.14)
        key=tuple(round(v*255) for v in rgb)
        if key not in materials:
            m=mat('Reference facet %s %s'%(obj.name,key),rgb)
            flat_color(m,rgb)
            materials[key]=len(obj.data.materials);obj.data.materials.append(m)
        face.material_index=materials[key]

def black_mouth_edges(obj,edges,origin):
    targets={frozenset(edge) for edge in edges}
    slot=len(obj.data.materials);obj.data.materials.append(mouth)
    for face in obj.data.polygons:
        points=frozenset((round((obj.data.vertices[i].co.x+origin[0])*140+300),
                          round(510-(obj.data.vertices[i].co.z+origin[1])*140)) for i in face.vertices)
        if points in targets:face.material_index=slot

leg_tucks=[];leg_swings=[]
def tube(name,path,radii,parent,mats=feetm,flight_path=None,swing_weights=None):
    verts=[];count=5
    for i,p in enumerate(path):
        p=Vector(p)
        direction=Vector(path[min(i+1,len(path)-1)])-Vector(path[max(0,i-1)])
        direction.normalize();a=Vector((0,1,0));b=direction.cross(a).normalized()
        for j in range(count):
            angle=math.tau*j/count
            verts.append(tuple(p+radii[i]*(a*math.cos(angle)+b*math.sin(angle))))
    faces=[]
    for i in range(len(path)-1):
        for j in range(count):faces.append((i*count+j,i*count+(j+1)%count,(i+1)*count+(j+1)%count,(i+1)*count+j))
    faces.extend([tuple(reversed(range(count))),tuple(range((len(path)-1)*count,len(path)*count))])
    o=mesh(name,verts,faces,mats,parent)
    if flight_path:
        o.shape_key_add(name='Basis');tuck=o.shape_key_add(name='Flight knee tuck')
        for i,p in enumerate(flight_path):
            p=Vector(p)
            direction=Vector(flight_path[min(i+1,len(path)-1)])-Vector(flight_path[max(0,i-1)])
            direction.normalize();a=Vector((0,1,0));b=direction.cross(a).normalized()
            for j in range(count):
                angle=math.tau*j/count
                tuck.data[i*count+j].co=p+radii[i]*.80*(a*math.cos(angle)+b*math.sin(angle))
        swing=o.shape_key_add(name='Flight leg adjustment');swing.slider_min=-1;swing.slider_max=1
        for i,vertex in enumerate(swing.data):
            weight=swing_weights[i//count]
            vertex.co=Vector(verts[i])+Vector((.06*weight,0,.035*weight))
        leg_tucks.append(tuck);leg_swings.append(swing)
    return o

root=empty('Raven • whole character',(0,0,1.3))
root.rotation_euler.z=-.55
torso=empty('Body • breathing and hops',(0,0,.12),root)
body=silhouette_body(reference_outline([
    (237,425),(223,403),(195,354),(206,280),(279,214),
    (313,168),(345,144),(399,137),(402,155),(398,176),
    (409,200),(413,245),(402,232),(407,274),(389,332),
    (352,383),(307,420),(275,424)
]),reference_interior([
    (356,163,.25),(375,166,.29),(362,196,.29),(332,216,.32),
    (369,250,.42),(376,295,.45),(344,333,.42),(282,372,.34),
    (289,409,.19),(289,314,.40),(267,263,.40),(311,236,.35),
    (314,177,.16),(359,144,.12),(388,144,.08),(248,365,.24)
]),torso,boundary_depths=[.004,.004,.004,.004,.004,.004,.004,.13,.18,.20,.15,.004,.004,.004,.004,.004,.004,.004,.004])
sampled_facet_colors(body)
black_mouth_edges(body,[[(402,155),(398,176)]],(0,1.42))
# The neutral torso is lean rather than changing from a puffed standing
# shape into a compressed flight shape. Preserve the skull and bill facets,
# trimming torso/neck-base radial depth and width around the spinal axis.
neutral_axis=Vector((.45,0,.79)).normalized();neutral_anchor=Vector((0,0,.05))
for vertex in body.data.vertices:
    p=vertex.co.copy();u=max(0,min(1,(p.z-.50)/.40));weight=1-u*u*(3-2*u)
    center=neutral_anchor+neutral_axis*(p-neutral_anchor).dot(neutral_axis)
    p=center+(p-center)*(1-.14*weight)
    p.y=vertex.co.y*(1-.16*weight)
    vertex.co=p
head=empty('Head • tilt and attention',(.45,0,.79),torso)
body_basis=[v.co.copy() for v in body.data.vertices]
body.shape_key_add(name='Basis')
flight_compression=0

def deform_neck():
    rotation=head.rotation_euler.to_matrix();pivot=head.location
    result=[]
    for p in body_basis:
        # Press the chest/neck and rump plumage against the long body axis
        # in flight. The head and the slimmer neutral silhouette stay intact.
        p=p.copy()
        weight=1-smooth((p.z-.49)/.40)
        axis=Vector((.45,0,.79)).normalized();anchor=Vector((0,0,.05))
        center=anchor+axis*(p-anchor).dot(axis)
        compressed=center+(p-center)*(.95 if p.z>.05 else .93)
        compressed.y=p.y*.96
        p=p.lerp(compressed,flight_compression*weight)
        weight=max(0,min(1,(p.z-.53)/.29))
        weight=weight*weight*(3-2*weight)
        moved=pivot+rotation@(p-pivot)
        result.append(p.lerp(moved,weight))
    return result

# The open bill follows the measured reference. A hinged upper jaw lowers to
# meet the lower jaw for the resting pose, preserving a continuous root.
bill_origin=from_reference(397,170)
upper=empty('Upper beak • caw',
            (bill_origin[0]-.45,0,bill_origin[1]-2.21),head)
upper_mesh=silhouette_body(reference_outline([
    (390,141),(411,136),(438,132),(454,134),(464,140),
    (430,148),(410,161),(397,173)
],bill_origin),reference_interior([
    (408,148,.17),(428,140,.10),(442,138,.045)
],bill_origin),upper,name='Heavy arched upper bill',z_offset=0,
    boundary_depths=[.18,.16,.08,.04,0,.08,.16,.20])
sampled_facet_colors(upper_mesh,bill_origin)
black_mouth_edges(upper_mesh,[[(464,140),(430,148)],[(430,148),(410,161)],
                            [(410,161),(397,173)]],bill_origin)
upper_mesh.shape_key_add(name='Basis')
closed_bill=upper_mesh.shape_key_add(name='Closed bill')
for vertex,source in zip(closed_bill.data,upper_mesh.data.vertices):
    # Both contours share the forehead attachment; the closed lower edge
    # meets the fixed lower jaw rather than leaving a wedge-shaped gap.
    open_points=[(390,141),(411,136),(438,132),(454,134),(464,140),
                 (430,148),(410,161),(397,173),(408,148),(428,140),(442,138)]
    closed_points=[(390,141),(411,151),(438,164),(454,174),(464,184),
                   (430,179),(410,174),(397,173),(408,155),(428,165),(442,172)]
    px=(source.co.x+bill_origin[0])*140+300
    py=510-(source.co.z+bill_origin[1])*140
    at=min(range(len(open_points)),key=lambda i:(px-open_points[i][0])**2+(py-open_points[i][1])**2)
    x,z=from_reference(*closed_points[at])
    vertex.co=(x-bill_origin[0],source.co.y,z-bill_origin[1])
bill=empty('Beak • speech',(bill_origin[0]-.45,0,bill_origin[1]-2.21),head)
lower_mesh=silhouette_body(reference_outline([
    (391,171),(422,177),(449,183),(462,186),(409,189),(390,182)
],bill_origin),reference_interior([
    (407,180,.15),(431,183,.065)
],bill_origin),bill,name='Tapered lower bill',z_offset=0,
    boundary_depths=[.19,.13,.065,0,.14,.19])
sampled_facet_colors(lower_mesh,bill_origin)
black_mouth_edges(lower_mesh,[[(391,171),(422,177)],[(422,177),(449,183)],
                            [(449,183),(462,186)]],bill_origin)
# Tiny matte eye patches lie on the actual head facets instead of sticking out.
bpy.context.view_layer.update()
head_vertices=[head.matrix_basis.inverted() @ v.co for v in body.data.vertices]
head_faces=[tuple(p.vertices) for p in body.data.polygons]
head_trees=[BVHTree.FromPolygons(head_vertices,head_faces)]
def eye_patch(name,side,rx,rz,material,offset):
    center=Vector((.16,side*.20,.276))
    normal=Vector((.62,side*.78,.05)).normalized()
    horizontal=Vector((.78,-side*.62,0)).normalized()
    vertical=normal.cross(horizontal).normalized()
    if vertical.z<0:vertical=-vertical
    tree=head_trees[0]
    pivot=tree.ray_cast(center+normal*.7,-normal,1.5)[0]+normal*offset
    circle=[Vector((rx*math.cos(i*math.tau/24),rz*math.sin(i*math.tau/24))) for i in range(24)]
    verts=[];triangles=[]
    def cross2(a,b):return a.x*b.y-a.y*b.x
    # Split the disk exactly along the underlying head triangles. A single
    # fan can dip through an adjacent head facet and appear to have holes.
    for face in head_faces:
        a,b,c=[head_vertices[i] for i in face]
        face_normal=(b-a).cross(c-a)
        denominator=face_normal.dot(normal)
        if abs(denominator)<1e-8:continue
        projected=[Vector(((p-center).dot(horizontal),(p-center).dot(vertical))) for p in [a,b,c]]
        orientation=1 if cross2(projected[1]-projected[0],projected[2]-projected[0])>0 else -1
        polygon=[p.copy() for p in circle]
        for edge_start,edge_end in zip(projected,projected[1:]+projected[:1]):
            clipped=[]
            for p,q in zip(polygon,polygon[1:]+polygon[:1]):
                dp=orientation*cross2(edge_end-edge_start,p-edge_start)
                dq=orientation*cross2(edge_end-edge_start,q-edge_start)
                if dp>=-1e-9:clipped.append(p)
                if (dp>=0)!=(dq>=0):clipped.append(p+(q-p)*(dp/(dp-dq)))
            polygon=clipped
            if len(polygon)<3:break
        if len(polygon)<3:continue
        def surface(p):
            ray=center+horizontal*p.x+vertical*p.y
            return ray+normal*(face_normal.dot(a-ray)/denominator)
        middle=sum(polygon,Vector((0,0)))/len(polygon)
        ray=center+horizontal*middle.x+vertical*middle.y
        hit=tree.ray_cast(ray+normal*.7,-normal,1.5)[0]
        if hit is None or (hit-surface(middle)).length>1e-5:continue
        start=len(verts)
        verts.extend(tuple(surface(p)+normal*offset-pivot) for p in polygon)
        triangles.extend((start,start+i,start+i+1) for i in range(1,len(polygon)-1))
    obj=mesh(name,verts,triangles,[material],head)
    obj.location=pivot
    return obj

eyes=[]
for side in [-1,1]:
    eye_patch('Eye socket '+str(side),side,.039,.039,black,.004)
    eyes.append(eye_patch('Silver eye '+str(side),side,.031,.032,eye,.006))

wings=[];wing_spreads=[];wing_flexes=[];wing_roll_tucks=[]
for side in [-1,1]:
    w=empty(('Left' if side==-1 else 'Right')+' wing • flap',(.032,side*.31,.317),torso)
    wings.append(w)
    outline=reference_outline([(304,264),(293,234),(252,244),(214,277),
             (177,310),(120,358),(144,355),(55,435),(113,416),
             (152,410),(230,384),(284,334),(299,289)],(.15,1.95))
    interior=reference_outline([(277,246),(254,251),(229,279),(220,282),
              (188,301),(247,277),(264,297),(232,311),(203,330),
              (162,351),(179,374),(125,400),(149,389),(110,418),
              (218,356),(241,338),(205,366)],(.15,1.95))
    wing=folded_wing_volume('Full-volume folded wing '+str(side),outline,interior,w,side)
    sampled_facet_colors(wing,(.15,1.95))
    wing_spreads.append(wing.data.shape_keys.key_blocks['Flight spread'])
    wing_flexes.append(wing.data.shape_keys.key_blocks['Feather flex'])
    wing_roll_tucks.append(wing.data.shape_keys.key_blocks['Roll elbow tuck'])

tail=empty('Tail • fan and balance',(-.48,0,-.39),torso)
tail_mesh=silhouette_body(reference_outline([(246,370),(197,380),(55,435),
              (82,438),(55,485),(89,476),(74,500),(140,470),(232,416),(260,393)],(-.48,1.03)),
              reference_interior([(166,440,.19),(213,402,.23),(99,477,.09),
                                  (121,461,.12),(183,417,.18),(154,446,.16),
                                  (136,430,.16),(102,451,.10),(180,405,.21)],(-.48,1.03)),tail,
              name='Continuous broad wedge tail',z_offset=0)
sampled_facet_colors(tail_mesh,(-.48,1.03))

legs=[];feet=[]
for side in [-1,1]:
    leg=empty('Leg '+str(side),(-.42 if side==-1 else .03,side*.18,-1.3),root);legs.append(leg)
    fx=side*.04;fy=side*.24;fz=side*.025
    tube('Feathered thigh '+str(side),[(-.12,0,.85),(-.12,0,.67),(-.10,0,.55)],[.070,.053,.042],leg,charcoal,
         flight_path=[(-.40+fx,fy,-.05),(-.25+fx,fy,-.31),(-.16+fx,fy,-.45)],swing_weights=[0,.15,.30])
    tube('Continuous ankle and tarsus '+str(side),[(-.10,0,.61),(-.035,0,.45),(.10,0,.20),(.27,0,.15)],[.047,.044,.039,.042],leg,
         flight_path=[(-.16+fx,fy,-.42),(-.16+fx,fy,-.58),(-.21+fx,fy,-.72+fz),(-.23+fx,fy,-.78+fz)],swing_weights=[.30,.55,.90,1])
    for j in [-1,0,1]:
        end=.36+(j+1)*.07
        tube('Curved toe %s %s'%(side,j),
             [(.25,0,.13),(.30+(j+1)*.04,j*.075,.14),
              (end,j*.14,.09),(end+.035,j*.14,.05)],
             [.039,.035,.028,.018],leg)
        tube('Hooked claw %s %s'%(side,j),
             [(end+.025,j*.14,.065),(end+.058,j*.14,.03),(end+.061,j*.14,.009)],
             [.020,.012,.001],leg,[black])
    tube('Curved rear toe '+str(side),
         [(.23,0,.13),(.045,-side*.04,.145),(-.055,-side*.04,.09),(-.10,-side*.04,.025)],
         [.034,.032,.021,.002],leg)
    foot=empty('Foot %s • ankle curl'%side,(.27,0,.15),leg);feet.append(foot)
    for part in list(leg.children):
        if part.type=='MESH' and part.name.startswith(('Curved toe','Hooked claw','Curved rear toe')):
            part.parent=foot;part.location=-foot.location.copy()

# Orthographic framing shared by every state, with ample room for wings.
bpy.ops.object.camera_add(location=(2,-12,3.4))
camera=bpy.context.object;camera.name='Sprite camera • fixed framing'
target=Vector((-.03,0,1.35));camera.rotation_euler=(target-camera.location).to_track_quat('-Z','Y').to_euler()
camera.data.type='ORTHO';camera.data.ortho_scale=3.75;scene.camera=camera

# An inspection camera shows the measured reference profile; sprite framing
# remains a separate camera so the requested 45-degree idle view is preserved.
turn=Matrix.Rotation(-.55,4,'Z')
bpy.ops.object.camera_add(location=turn@Vector((-.28,-12,1.36)))
reference_camera=bpy.context.object;reference_camera.name='Reference camera • perched profile'
reference_camera.data.type='ORTHO';reference_camera.data.ortho_scale=3.60
reference_target=turn@Vector((-.28,0,1.36))
reference_camera.rotation_euler=(reference_target-reference_camera.location).to_track_quat('-Z','Y').to_euler()

inspection_cameras={}
for name,position in {'quarter':(8,-10,4),'front':(12,0,3),'underside':(3,-7,-8),'above':(2,-5,12)}.items():
    target=Vector((-.45,0,3.25));position=Matrix.Rotation(-.55,4,'Z')@Vector(position)+target
    bpy.ops.object.camera_add(location=position)
    c=bpy.context.object;c.name='Flight inspection • '+name
    c.rotation_euler=(target-position).to_track_quat('-Z','Y').to_euler()
    c.data.type='ORTHO';c.data.ortho_scale={'quarter':16.3,'front':10.5,'underside':17.6,'above':17.7}[name]
    inspection_cameras[name]=c

def light(name,loc,power,size):
    bpy.ops.object.light_add(type='AREA',location=loc)
    l=bpy.context.object;l.name=name;l.data.energy=power;l.data.shape='DISK';l.data.size=size
    l.rotation_euler=(Vector((0,0,1.4))-l.location).to_track_quat('-Z','Y').to_euler()
light('Soft key',(-3,-4,6),650,4)
light('Rim',(2,4,5),950,3)
light('Gentle face fill',(4,-2,2.7),150,3)
scene.world.use_nodes=True
scene.world.node_tree.nodes.get('Background').inputs['Color'].default_value=(1,1,1,1)
scene.world.node_tree.nodes.get('Background').inputs['Strength'].default_value=1
scene.render.engine='CYCLES'
scene.cycles.samples=16
scene.cycles.use_denoising=True
scene.render.resolution_x=256;scene.render.resolution_y=256;scene.render.resolution_percentage=100
scene.render.film_transparent=True
scene.render.image_settings.file_format='PNG';scene.render.image_settings.color_mode='RGBA'
scene.view_settings.view_transform='Standard'
scene.view_settings.exposure=0
scene.render.fps=8

clips={
    'idle':(200,8,True),
    'soaring':(160,8,True),
    'takeoff':(32,8,False),
    'working_flip':(40,8,False),
    'speaking':(12,8,True),
    'waiting':(36,8,True),
    'idle_blink':(6,8,False),
    'idle_glance':(24,8,False),
    'soar_intro':(12,8,False),
    'diving':(56,8,False),
    'patrol_roll':(40,8,False),
}
animated=[root,torso,head,upper,bill,tail,*wings,*legs,*feet,*eyes]
base={o.name:(o.location.copy(),o.rotation_euler.copy(),o.scale.copy()) for o in animated}
camera_base=camera.location.copy()

def smooth(value):
    value=max(0,min(1,value));return value*value*(3-2*value)

def bump(seconds,start,duration):
    u=(seconds-start)/duration
    if u<=0 or u>=1:return 0
    return math.sin(math.pi*u)**2

PATROL_HALF_LENGTH=4.4
PATROL_SWAY=.70
PATROL_PASS_TIME=7.5
PATROL_TURN_TIME=2.5
PATROL_START_HEADING=math.atan2(-4*math.pi*PATROL_SWAY,2*PATROL_HALF_LENGTH)
PATROL_SPEED=math.hypot(2*PATROL_HALF_LENGTH,4*math.pi*PATROL_SWAY)/PATROL_PASS_TIME
PATROL_TURN_RADIUS=PATROL_SPEED*PATROL_TURN_TIME/math.pi
PATROL_JOIN_CURVATURE=-( (2*PATROL_HALF_LENGTH)**2+(4*math.pi*PATROL_SWAY)**2 )/(2*PATROL_HALF_LENGTH)*math.pi*PATROL_PASS_TIME/PATROL_TURN_TIME
FLIGHT_SCALE=17.2

def turn_displacement(u,heading):
    # Circular course: constant speed and turning rate throughout the U-turn.
    angle=heading-math.pi*u
    return PATROL_TURN_RADIUS*Vector((math.sin(heading)-math.sin(angle),math.cos(angle)-math.cos(heading),0))

PATROL_TURN_OFFSET=turn_displacement(1,PATROL_START_HEADING)
FLIGHT_TARGET=Matrix.Rotation(-.55,4,'Z')@Vector((PATROL_TURN_OFFSET.x/2,0,3.25))

def base_weave(u):
    q=4*math.pi
    return (-PATROL_SWAY*math.sin(q*u),-q*PATROL_SWAY*math.cos(q*u),
            q*q*PATROL_SWAY*math.sin(q*u),q**3*PATROL_SWAY*math.cos(q*u))

def hermite_coefficients(left,right,width):
    # Seventh-degree Hermite course: match position, tangent, curvature and
    # curvature change. The last swerve rolls directly into the circular turn.
    c=[left[0],left[1]*width,left[2]*width**2/2,left[3]*width**3/6]
    target=[right[0]-sum(c),right[1]*width-(c[1]+2*c[2]+3*c[3]),
            right[2]*width**2-(2*c[2]+6*c[3]),right[3]*width**3-6*c[3]]
    matrix=[[1,1,1,1],[4,5,6,7],[12,20,30,42],[24,60,120,210]]
    for i in range(4):
        pivot=matrix[i][i]
        matrix[i]=[v/pivot for v in matrix[i]];target[i]/=pivot
        for j in range(4):
            if j==i:continue
            factor=matrix[j][i]
            matrix[j]=[a-factor*b for a,b in zip(matrix[j],matrix[i])]
            target[j]-=factor*target[i]
    return c+target

PATROL_JOIN_WIDTH=.25
join_slope=-4*math.pi*PATROL_SWAY
join_third=2*join_slope*PATROL_JOIN_CURVATURE**2/((2*PATROL_HALF_LENGTH)**2+join_slope**2)
join=(0,join_slope,PATROL_JOIN_CURVATURE,join_third)
first_join=hermite_coefficients(join,base_weave(PATROL_JOIN_WIDTH),PATROL_JOIN_WIDTH)
last_join=hermite_coefficients(base_weave(1-PATROL_JOIN_WIDTH),join,PATROL_JOIN_WIDTH)

def woven_curve(u):
    if u<PATROL_JOIN_WIDTH:co=first_join;v=u/PATROL_JOIN_WIDTH
    elif u>1-PATROL_JOIN_WIDTH:co=last_join;v=(u-(1-PATROL_JOIN_WIDTH))/PATROL_JOIN_WIDTH
    else:return base_weave(u)[:3]
    return (sum(c*v**i for i,c in enumerate(co)),
            sum(i*co[i]*v**(i-1) for i in range(1,8))/PATROL_JOIN_WIDTH,
            sum(i*(i-1)*co[i]*v**(i-2) for i in range(2,8))/PATROL_JOIN_WIDTH**2)

def bank_for_rate(rate):
    turn_rate=math.pi/PATROL_TURN_TIME
    return -.32*math.tanh(rate/turn_rate)/math.tanh(1)

def woven_pass(u,returning=False):
    sway,slope,curvature=woven_curve(u)
    if returning:
        position=Vector((PATROL_HALF_LENGTH-2*PATROL_HALF_LENGTH*u,.60-sway,0))+PATROL_TURN_OFFSET
        heading=-math.pi+math.atan2(slope,2*PATROL_HALF_LENGTH)
    else:
        position=Vector((-PATROL_HALF_LENGTH+2*PATROL_HALF_LENGTH*u,.60+sway,0))
        heading=math.atan2(slope,2*PATROL_HALF_LENGTH)
    rate=(2*PATROL_HALF_LENGTH)*curvature/((2*PATROL_HALF_LENGTH)**2+slope**2)/PATROL_PASS_TIME
    bank=bank_for_rate(rate)
    # Half the previous vertical excursion, independent of the turn correction.
    rise=math.sin(4*math.pi*u)**2*(1.1+.075*math.sin(8*math.pi*u))
    return position,heading,bank,rise

def flight_pose(t,initial=False):
    global flight_compression
    flight_compression=1
    phase=t*2;wind=math.sin(math.tau*phase);trim=math.sin(math.tau*phase*2)
    # Two linked eights along each 7.5-second pass, with a 2.5-second
    # U-turn at either end. The fixed observer sees the bird steer both
    # toward and away from the camera as it crosses the chat window.
    rise=0
    if t<.375:
        position,heading,bank,rise=woven_pass(t/.375)
    elif t<.5:
        u=(t-.375)/.125
        position=Vector((PATROL_HALF_LENGTH,.60,0))+turn_displacement(u,PATROL_START_HEADING)
        heading=PATROL_START_HEADING-math.pi*u;bank=bank_for_rate(-math.pi/PATROL_TURN_TIME)
        rise=.15*math.sin(math.pi*u)**2
    elif t<.875:
        position,heading,bank,rise=woven_pass((t-.5)/.375,returning=True)
    else:
        u=(t-.875)/.125
        position=Vector((-PATROL_HALF_LENGTH,.60,0))+PATROL_TURN_OFFSET+turn_displacement(u,PATROL_START_HEADING-math.pi)
        heading=PATROL_START_HEADING-math.pi-math.pi*u;bank=bank_for_rate(-math.pi/PATROL_TURN_TIME)
        rise=.15*math.sin(math.pi*u)**2
    root.location=Matrix.Rotation(-.55,4,'Z')@position
    root.location.z=2.13+rise+.0225*wind+.005*trim
    bank+=.025*wind
    heading-=.55
    root.rotation_euler=(Matrix.Rotation(heading,4,'Z')@Matrix.Rotation(bank,4,'X')).to_euler()
    # The perched spine leans forward already: a 52-degree body rotation
    # places its long axis about ten degrees above the horizon.
    torso.rotation_euler.y=.90+.018*wind
    torso.scale.z=1
    scan=math.sin(math.tau*4*t)
    roll,look_pitch,yaw=.045*scan,1.10+.20*scan**2,-.50*scan
    if initial:roll,look_pitch,yaw=0,-.12,0
    # Yaw before the downward pitch tips the selected eye toward the ground
    # as well as turning the bill, giving three distinct downward scans.
    head.rotation_euler=(Matrix.Rotation(-torso.rotation_euler.y,4,'Y')@
                         Matrix.Rotation(look_pitch,4,'Y')@Matrix.Rotation(yaw,4,'Z')@
                         Matrix.Rotation(roll,4,'X')).to_euler()
    tail.rotation_euler.y=-.57+.012*wind
    tail.rotation_euler.z=.014*trim
    for w,side in zip(wings,[-1,1]):
        # Seat each shoulder inside the compressed flight chest.
        w.location.y=side*.26
        # A steady dihedral with tiny independent trim changes, never flaps.
        flap=side*(.24+.016*wind+side*.008*trim)
        wing_pitch=1.35-torso.rotation_euler.y+.010*trim
        w.rotation_euler=(Matrix.Rotation(wing_pitch,4,'Y')@Matrix.Rotation(flap,4,'Z')@
                          Matrix.Rotation(side*.013*trim,4,'X')).to_euler()
    for key in wing_spreads:key.value=1
    for key,side in zip(wing_flexes,[-1,1]):key.value=.18*math.sin(math.tau*phase+side*.6)
    for leg,foot,side in zip(legs,feet,[-1,1]):
        adjustment=math.sin(math.tau*phase+side*.7)
        leg.location=(0,0,0);leg.rotation_euler=(0,0,0);leg.scale=(1,1,1)
        foot.location=(-.23+side*.04+.06*adjustment,side*.24,-.78+side*.025+.035*adjustment)
        foot.scale=(.82,.82,.82)
        foot.rotation_euler.y=1.95+.14*math.cos(math.tau*phase+side*.7)
        foot.rotation_euler.x=side*.06*math.sin(math.tau*phase)
    for key in leg_tucks:key.value=1
    for i,key in enumerate(leg_swings):key.value=math.sin(math.tau*phase+(-1 if i<2 else 1)*.7)

def flight_camera(t):
    # Fixed observer, just below the flight plane. A steep underside view
    # projected the far wing onto the belly and hid the shins in profile.
    local=Vector((PATROL_TURN_OFFSET.x/2+.65,-12,0))
    position=Matrix.Rotation(-.55,4,'Z')@local
    position.z=2.95
    return position

def dive_pose(t):
    global flight_compression
    # Capture the exact accepted perch, including its original camera. The
    # landing ends on this pose, so the browser can hand over to idle cleanly.
    pose('idle',0)
    ground={o.name:(o.location.copy(),o.rotation_euler.copy(),o.scale.copy()) for o in animated}
    ground_camera=camera.location.copy()
    flight_pose(0,initial=True)
    brake=smooth((t-.22)/.24)
    settle=smooth((t-.46)/.29)
    deploy=smooth((t-.43)/.23)
    fold=smooth((t-.62)/.28)
    torso.rotation_euler.y=1.30-.45*brake
    head.rotation_euler=(Matrix.Rotation(-torso.rotation_euler.y,4,'Y')@
                         Matrix.Rotation(.24*(1-brake),4,'Y')).to_euler()
    for o in animated:
        if o is root or o in wings:continue
        weight=deploy if o in legs+feet else settle
        l,r,s=ground[o.name]
        o.location=o.location.lerp(l,weight)
        o.rotation_euler=Vector(o.rotation_euler).lerp(Vector(r),weight)
        o.scale=o.scale.lerp(s,weight)
    root.location=(.16*math.sin(math.pi*t)*(1-settle),.75*(1-smooth(t/.65)),
                   1.30+2.9*(1-smooth(t/.65)))
    front=math.atan2(ground_camera.y-root.location.y,ground_camera.x-root.location.x)
    turn=smooth((t-.62)/.28)
    root.rotation_euler=(0,0,front+(ground[root.name][1].z-front)*turn)
    head.rotation_euler.z+=(front-root.rotation_euler.z)*(1-smooth((t-.80)/.10))
    crouch=.065*bump(t,.62,.20)**2
    root.location.z-=crouch
    for o in legs+feet:o.location.z+=crouch
    flight_compression=1-settle
    tail.rotation_euler.y=ground[tail.name][1].y-.57*(1-settle)
    tail.rotation_euler.z=0
    for wing,side in zip(wings,[-1,1]):
        # High symmetrical V during the fall; spread into a braking glide,
        # then fold the same three-dimensional wings after the feet reach down.
        raised=.95-.73*brake
        twist=.18+.95*brake-torso.rotation_euler.y
        flight_rotation=(Matrix.Rotation(twist,4,'Y')@
                         Matrix.Rotation(side*raised,4,'X')).to_euler()
        l,r,s=ground[wing.name]
        wing.rotation_euler=Vector(flight_rotation).lerp(Vector(r),fold)
        wing.location=Vector((l.x,side*.26,l.z)).lerp(l,fold)
    for key in wing_spreads:key.value=1-fold
    for key in wing_flexes:key.value=-.12*(1-fold)*brake
    for key in leg_tucks:key.value=1-deploy
    for key in leg_swings:key.value*=1-deploy
    for eye_object in eyes:eye_object.scale.z=1-.92*bump(t,.84,.08)**2
    # Keep the observer still through the descent. Once perched, gently
    # settle the framing into the existing idle camera rather than cutting.
    framing=smooth((t-.72)/.20)
    camera.location=ground_camera+Vector((0,0,1.05*(1-framing)))
    camera.data.ortho_scale=9.6+(3.75-9.6)*framing
    return Vector((-.03,0,1.35+1.05*(1-framing)))

def pose(state,t):
    global flight_compression
    flight_compression=0
    for o in animated:
        l,r,s=base[o.name];o.location=l.copy();o.rotation_euler=r.copy();o.scale=s.copy()
    wave=math.sin(t*2*math.pi); breath=math.sin(t*2*math.pi)
    torso.scale.z=1+.008*breath
    head.rotation_euler.y=.018*wave
    closed_bill.value=1
    for key in wing_spreads:key.value=0
    for key in wing_flexes:key.value=0
    for key in wing_roll_tucks:key.value=0
    for key in leg_tucks+leg_swings:key.value=0
    camera.location=camera_base.copy()
    camera.data.ortho_scale=3.75
    view_target=Vector((-.03,0,1.35))
    if state=='idle':
        seconds=t*25
        # Five distinct gazes, held until the next turn about five seconds later.
        gazes=[(0,0,0),(.20,-.13,-.42),(-.16,.14,-.84),
               (.16,-.16,-1.27),(-.20,.10,-.64)]
        index=int(seconds//5)%5
        turn=smooth(((seconds%5)-4.625)/.375)
        head.rotation_euler=Vector(gazes[index]).lerp(Vector(gazes[(index+1)%5]),turn)
        shut=max(bump(seconds,start,.375)**2 for start in [3.0625,8.6875,14.1875,21.3125])
        for eye_object in eyes:eye_object.scale.z=1-.98*shut
        torso.scale.z=1+.003*math.sin(seconds*math.tau/5)
    elif state=='idle_blink':
        shut=math.sin(math.pi*t)**4
        for e in eyes:e.scale.z=base[e.name][2].z*(1-.91*shut)
    elif state=='idle_glance':
        head.rotation_euler.z=-1.5*math.sin(math.pi*t)**2
        head.rotation_euler.x=.055*math.sin(math.pi*t)
    elif state in ['soaring','working_flip','soar_intro','patrol_roll']:
        flight_pose(t if state=='soaring' else t*39/160 if state=='patrol_roll' else 0)
        if state=='soar_intro':
            look_pitch=-.12+1.22*smooth((t-.12)/.63)
            head.rotation_euler=(Matrix.Rotation(-torso.rotation_euler.y,4,'Y')@
                                 Matrix.Rotation(look_pitch,4,'Y')).to_euler()
        camera.location=flight_camera(t if state=='soaring' else 0)
        camera.data.ortho_scale=FLIGHT_SCALE
        view_target=FLIGHT_TARGET.copy()
        if state in ['working_flip','patrol_roll']:
            # Roll about the pitched head-to-tail axis, keeping the body
            # centre in place. No camera zoom or tracking during the gesture.
            if t<.40:angle=math.pi*smooth(t/.40)
            elif t<.58:angle=math.pi
            else:angle=math.pi+math.pi*smooth((t-.58)/.28)
            axis=Matrix.Rotation(.90,4,'Y')@Vector((.45,0,.79)).normalized()
            rotation=Matrix.Rotation(angle,4,axis)
            heading=root.rotation_euler.to_matrix().to_4x4()
            root.rotation_euler=(heading@rotation).to_euler()
            pivot=Vector((0,0,.12))
            root.location+=heading@(pivot-rotation@pivot)
            drift=math.sin(math.pi*t)**2
            root.location+=heading@Vector((-.16*drift,0,.09*drift))
            # Fold while turning: the wing tuck shares the roll's onset.
            tuck=smooth(t/.24)*(1-smooth((t-.82)/.18))
            hold=smooth((t-.36)/.04)*(1-smooth((t-.58)/.06))
            tuck*=1-.32*hold
            for wing,side in zip(wings,[-1,1]):
                dihedral=side*(.24+.18*tuck)
                folded=(Matrix.Rotation(.45,4,'Y')@
                                     Matrix.Rotation(dihedral,4,'Z')@
                                     Matrix.Rotation(-side*.12*tuck,4,'X')).to_quaternion()
                wing.rotation_euler=(wing.rotation_euler.to_quaternion().slerp(folded,tuck).to_euler()
                                     if state=='patrol_roll' else folded.to_euler())
            for key in wing_roll_tucks:key.value=tuck
            for key,side in zip(wing_flexes,[-1,1]):
                key.value=(key.value if state=='patrol_roll' else .18*math.sin(side*.6))-.26*tuck
            for foot in feet:foot.rotation_euler.y+=.25*tuck
    elif state=='diving':
        view_target=dive_pose(t)
    elif state=='takeoff':
        flight_pose(0,initial=True)
        goal={o.name:(o.location.copy(),o.rotation_euler.copy(),o.scale.copy()) for o in animated}
        lift=smooth((t-.125)/.60);unfold=smooth((t-.08)/.32)
        pitch=smooth((t-.16)/.60);tuck=smooth((t-.25)/.45)
        flight_compression=pitch
        for o in animated:
            weight=tuck if o in legs+feet else pitch
            l,r,s=base[o.name];gl,gr,gs=goal[o.name]
            o.location=l.lerp(gl,weight);o.rotation_euler=Vector(r).lerp(Vector(gr),weight)
            o.scale=s.lerp(gs,weight)
        root.location.z=1.30+(goal[root.name][0].z-1.30)*lift
        crouch=bump(t,0,.22)
        root.location.z-=.085*crouch
        for leg in legs:leg.location.z+=.085*crouch*(1-tuck)
        torso.scale.z=1-.025*crouch
        flap_gate=smooth((t-.10)/.13)*(1-smooth((t-.78)/.16))
        flap_phase=max(0,min(3,(t-.125)/.70*3))*math.tau
        for w,side in zip(wings,[-1,1]):
            flap=side*(.24*unfold+.78*flap_gate*math.sin(flap_phase))
            w.rotation_euler=(Matrix.Rotation(.45*pitch,4,'Y')@Matrix.Rotation(flap,4,'Z')).to_euler()
        for key in wing_spreads:key.value=unfold
        for key,side in zip(wing_flexes,[-1,1]):
            key.value=-.85*flap_gate*math.cos(flap_phase)+.18*math.sin(side*.6)*(1-flap_gate)*unfold
        for key in leg_tucks:key.value=tuck
        for i,key in enumerate(leg_swings):key.value=tuck*math.sin((-1 if i<2 else 1)*.7)
        camera.location=camera_base.lerp(flight_camera(0),unfold)
        camera.data.ortho_scale=3.75+(FLIGHT_SCALE-3.75)*unfold
        view_target=Vector((-.03,0,1.35)).lerp(FLIGHT_TARGET,lift)
    elif state=='speaking':
        camera.data.ortho_scale=2.1
        view_target=Vector((.33,-.12,2.30))
        opening=.5-.5*math.cos(t*4*math.pi)
        closed_bill.value=1-opening
        bill.rotation_euler.y=.025+.08*opening
        head.rotation_euler.y=-.07+.055*math.sin(t*4*math.pi)
        head.rotation_euler.z=-.22
        torso.scale.z=1+.014*wave
    elif state=='waiting':
        camera.data.ortho_scale=2.1
        view_target=Vector((.33,-.12,2.30))
        head.rotation_euler.z=-.84+.65*math.cos(t*2*math.pi)
        head.rotation_euler.x=.04*math.sin(t*2*math.pi)
        # Quick, straight blink on one pass through the forward gaze.
        shut=max(0,1-abs(t-.75)/.035)
        for e in eyes:e.scale.z=base[e.name][2].z*(1-.9*shut)
    camera.rotation_euler=(view_target-camera.location).to_track_quat('-Z','Y').to_euler()

manifest={'frameWidth':256,'frameHeight':256,'columns':12,'states':['idle','working','speaking','waiting'],
          'stateClips':{'idle':'idle','working':'soaring','speaking':'speaking','waiting':'waiting'},'clips':{}}
start=1;row=0
for state,(count,fps,loop) in clips.items():
    scene.timeline_markers.new(state,frame=start)
    manifest['clips'][state]={'row':row,'frames':count,'fps':fps,'loop':loop,'startFrame':start}
    if state=='idle':
        for gaze in range(5):scene.timeline_markers.new('Idle gaze %d'%(gaze+1),frame=start+gaze*40)
    if state=='working_flip':
        for offset,label in [(1,'Roll • turn and fold'),(16,'Roll • inverted glide'),(23,'Roll • recover'),(34,'Roll • wings reopen')]:
            scene.timeline_markers.new(label,frame=start+offset)
    if state=='diving':
        for offset,label in [(0,'Dive • raised wings'),(20,'Dive • braking glide'),(35,'Dive • feet reach down'),(43,'Dive • wings fold'),(55,'Dive • perched')]:
            scene.timeline_markers.new(label,frame=start+offset)
    previous_root_rotation=None
    for f in range(count+1):
        t=(f%count)/count if loop else min(f,count-1)/(count-1)
        scene.frame_set(start+f);pose(state,t)
        if state in ['working_flip','soaring','patrol_roll']:
            if previous_root_rotation is not None:
                root.rotation_euler=root.rotation_euler.to_matrix().to_euler('XYZ',previous_root_rotation)
            previous_root_rotation=root.rotation_euler.copy()
        closed_bill.keyframe_insert(data_path='value',frame=start+f)
        for key in wing_spreads+wing_flexes+wing_roll_tucks+leg_tucks+leg_swings:key.keyframe_insert(data_path='value',frame=start+f)
        shape=body.shape_key_add(name='%s %03d'%(state,f))
        for vertex,co in zip(shape.data,deform_neck()):vertex.co=co
        for at,value in [(start+f-1,0),(start+f,1),(start+f+1,0)]:
            shape.value=value;shape.keyframe_insert(data_path='value',frame=at)
        for o in animated:
            for prop in ['location','rotation_euler','scale']:o.keyframe_insert(data_path=prop,frame=start+f)
        camera.keyframe_insert(data_path='location',frame=start+f)
        camera.keyframe_insert(data_path='rotation_euler',frame=start+f)
        camera.data.keyframe_insert(data_path='ortho_scale',frame=start+f)
    row+=math.ceil(count/12)
    start+=count+4
# A full-body caw pose makes the reference comparison directly inspectable.
reference_frame=start+2
scene.frame_set(reference_frame);pose('idle',0)
head.rotation_euler=(0,0,0);closed_bill.value=0
for o in animated:
    for prop in ['location','rotation_euler','scale']:
        o.keyframe_insert(data_path=prop,frame=reference_frame)
for key in body.data.shape_keys.key_blocks[1:]:
    key.value=0;key.keyframe_insert(data_path='value',frame=reference_frame)
closed_bill.keyframe_insert(data_path='value',frame=reference_frame)
for key in wing_spreads+wing_flexes+wing_roll_tucks+leg_tucks+leg_swings:key.keyframe_insert(data_path='value',frame=reference_frame)
scene.timeline_markers.new('Reference • full-body caw',frame=reference_frame)
scene.frame_start=1;scene.frame_end=reference_frame
scene.frame_set(reference_frame)
scene['Reference pose frame']=reference_frame
scene['README']='8 fps: idle gazes, three-flap takeoff, upright introduction, then a 20-second patrol with half-height rises. Reshaped swerves join constant-rate 2.5-second banked U-turns; outer wing stays high. Continuous downward scan cone. Synchronized wing tuck/roll. Separate seven-second frontal raised-wing dive, braking glide and exact landing-to-idle. Two palettes.'
for area in bpy.context.screen.areas:
    if area.type=='VIEW_3D':
        space=area.spaces.active
        space.region_3d.view_perspective='CAMERA'
        space.use_local_camera=False;space.camera=camera
        space.shading.type='MATERIAL';space.shading.use_scene_world=True
        space.overlay.show_overlays=False
bpy.ops.object.select_all(action='DESELECT')
body.select_set(True);bpy.context.view_layer.objects.active=body
blend=OUT/'raven.blend'
scene.camera=camera
set_palette(False)
scene.frame_set(1)
bpy.ops.wm.save_as_mainfile(filepath=str(blend))
(OUT/'sprites.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
scene.camera=camera
from bpy_extras.object_utils import world_to_camera_view
screen_path=[];plan_path=[]
for f in range(clips['soaring'][0]+1):
    scene.frame_set(manifest['clips']['soaring']['startFrame']+f)
    bpy.context.view_layer.update()
    screen=world_to_camera_view(scene,camera,root.matrix_world.translation)
    screen_path.append([round(screen.x*256,2),round((1-screen.y)*256,2)])
    point=Matrix.Rotation(.55,4,'Z')@root.location
    plan_path.append([round(point.x,4),round(point.y,4),round(point.z,4)])
(OUT/'patrol-path.json').write_text(json.dumps({'duration':20,'fps':8,'weavesPerPass':2,
    'screen':screen_path,'plan':plan_path,
    'screenPath':'M'+' L'.join('%s %s'%tuple(p) for p in screen_path)},indent=2),encoding='utf-8')
scene.frame_set(1)

for darker in [False,True]:
    scene.render.resolution_x=256;scene.render.resolution_y=256
    set_palette(darker)
    if darker:
        scene.frame_set(1);scene.camera=camera
        bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'raven-darker.blend'))
    scene.camera=camera
    suffix='-darker' if darker else ''
    if '--views' in sys.argv and not darker:
        destination=OUT/'flight-views';destination.mkdir(exist_ok=True)
        for name,c in inspection_cameras.items():
            if '--view-names' in sys.argv and name not in sys.argv[sys.argv.index('--view-names')+1].split(','):continue
            scene.camera=c
            for f in (0,10,17,30,34,74,112,154) if '--test' in sys.argv else range(clips['soaring'][0]):
                scene.frame_set(manifest['clips']['soaring']['startFrame']+f)
                scene.render.filepath=str(destination/('%s-%02d.png'%(name,f)))
                bpy.ops.render.render(write_still=True)
        scene.camera=camera
    if '--test' in sys.argv:
        for state,offset in [('idle',0),('idle',40),('idle',80),('idle',120),('idle',160),('soaring',0),('soaring',16),('soaring',24),('soaring',32),('soaring',40),('soaring',48),('soaring',64),('soaring',72),('soaring',88),('takeoff',8),('takeoff',16),('takeoff',24),('takeoff',31)]:
            scene.frame_set(manifest['clips'][state]['startFrame']+offset)
            scene.render.filepath=str(OUT/('preview-'+state+'-%02d'%offset+suffix+'.png'))
            bpy.ops.render.render(write_still=True)
    else:
        detail='--detail' in sys.argv
        if detail:scene.render.resolution_x=512;scene.render.resolution_y=512
        destination=OUT/(('flight-detail' if detail else 'frames')+suffix);destination.mkdir(exist_ok=True)
        for state,data in manifest['clips'].items():
            if detail and state not in ['soaring','takeoff','working_flip','soar_intro','diving','patrol_roll']:continue
            if '--clips' in sys.argv and state not in sys.argv[sys.argv.index('--clips')+1].split(','):continue
            for f in range(data['frames']):
                scene.frame_set(data['startFrame']+f)
                scene.render.filepath=str(destination/('%s-%02d.png'%(state,f)))
                bpy.ops.render.render(write_still=True)
                print('SPRITE',suffix or 'current',state,f,flush=True)
        print('RAVEN_RENDER_COMPLETE',suffix or 'current',flush=True)
