"""v24 full-body near-head attention library, using the native button-perch rig.

Blender --background --threads 2 --python build_chat_attention.py
Same 450-pose blink/tilt/pitch/yaw grid as the approved cursor interaction.
Pass -- --scout for the six inspection poses, or --timeline-only to bake only.
"""
import bpy, json, sys, argparse, importlib.util, shutil
from pathlib import Path
P=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('native_chat_perch_rig',P/'build_chat_perch.py')
rig=importlib.util.module_from_spec(spec);spec.loader.exec_module(rig)
scene=rig.scene;scene.render.resolution_x=scene.render.resolution_y=256
parser=argparse.ArgumentParser();parser.add_argument('--scout',action='store_true');parser.add_argument('--timeline-only',action='store_true')
args=parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
destination=P/'chat-attention-frames';destination.mkdir(exist_ok=True)
scouts=[0,8,115,224,340,449]
metadata={'version':24,'baseSourceSha256':rig.CHAT_BASE_SHA,'frameWidth':256,'frameHeight':256,
          'columns':12,'frames':450,'fps':8,'yaw':rig.head_yaws,'pitch':rig.head_pitches,'tilt':rig.head_tilts,
          'blinkLayers':2,'order':['blink','tilt','pitch','yaw'],'poses':[],
          'sourcePattern':'chat-attention-frames/attention-%03d.png',
          'camera':{'location':list(rig.CHAT_CAMERA[0]),'rotation':list(rig.CHAT_CAMERA[1]),'orthoScale':3.75},
          'description':'Full-body native near-head attention poses with the latest slim model and 3D curled claws; same camera/contact as idle. Draw the whole sprite, never patch an older head onto it.'}
cache={}
for index in range(450):
    frame=index+1;scene.frame_set(frame);info=rig.apply_attention(index)
    metadata['poses'].append(rig.pose_metadata(info));rig.bake_frame(frame,f'attention {index:03d}')
    if not args.timeline_only and (not args.scout or index in scouts):
        path=destination/f'attention-{index:03d}.png';key=rig.render_fingerprint()
        if key in cache:shutil.copyfile(cache[key],path)
        else:
            scene.render.filepath=str(path);bpy.ops.render.render(write_still=True);cache[key]=path
        print('CHAT_ATTENTION',index+1,'/450',flush=True)
metadata['renderedUniquePoses']=len(cache)
if not args.scout:
    rig.finalise_timeline(P/'raven-chat-attention-v24.blend',450,'v24 native full-body cursor head library. 450 blink/tilt/pitch/yaw poses, latest shared base, fixed 3.75 camera and curled Send-button claws. Use only near the head and return to normal idle away from it.')
    (P/'chat-attention.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
else:(P.parent.parent/'work'/'chat-attention-scout-v24.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
print('CHAT_ATTENTION_COMPLETE',450,'logical poses;',len(cache),'native renders',flush=True)
