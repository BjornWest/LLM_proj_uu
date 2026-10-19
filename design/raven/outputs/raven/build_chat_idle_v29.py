"""Native 60 fps idle with twice-as-fast head turns and unchanged cadence.

Blender --background --threads 6 --python build_chat_idle_v29.py
Use -- --scout to inspect changed poses before building the full timeline.
The five turns keep their original 4.625 + n*5 second onsets, but reach
their targets after 0.1875 rather than 0.375 seconds. Only the head/neck
changes; breathing, blink times, gripping feet, body and camera are kept.
Exact evaluated-geometry and render-provenance matches reuse v26 pixels.
"""
import bpy, json, sys, argparse, shutil, hashlib, importlib.util
from pathlib import Path
from mathutils import Vector

P=Path(__file__).resolve().parent
WORK=P.parents[1]/'work'
FPS=60
BASE_SHA='4fa42b8172433fea1bf31ff4a3eb0d5da08126ff2d62c750055b2ad77670f42b'
GAZES=[(0,0,0),(.20,-.13,-.42),(-.16,.14,-.84),(.16,-.16,-1.27),(-.20,.10,-.64)]
TURN_START=4.625
OLD_TURN_SECONDS=.375
TURN_SECONDS=OLD_TURN_SECONDS/2
COUNTS={'perch':1,'idle':1500}
INSPECTION={'perch':[0], 'idle':[0,277,278,282,288,289,299,300,578,588,589,878,888,889,1178,1188,1189,1478,1488,1489,1498,1499]}

spec=importlib.util.spec_from_file_location('v26_idle_helpers',P/'build_chat_perch_v26.py')
helpers=importlib.util.module_from_spec(spec);spec.loader.exec_module(helpers)
base_apply_pose=helpers.apply_pose

def apply_pose(clip,index):
    info=base_apply_pose(clip,index)
    if clip=='idle':
        seconds=index/FPS
        phase=seconds%5
        gaze=int(seconds//5)%5
        # Preserve every accepted pose outside the shorter head turn exactly.
        if phase>TURN_START and index!=1499:
            weight=rig.smooth((phase-TURN_START)/TURN_SECONDS)
            rig.head.rotation_euler=Vector(GAZES[gaze]).lerp(Vector(GAZES[(gaze+1)%5]),weight)
            for vertex,co in zip(rig.live_neck.data,rig.neck_coordinates()):vertex.co=co
            rig.live_neck.value=1;bpy.context.view_layer.update()
        info.update(headTurnSpeed=2,headTurnSeconds=TURN_SECONDS,headTurnOnset=TURN_START+5*gaze,
                    headTarget=(gaze+1)%5 if phase>TURN_START else gaze,
                    label='Twice-as-fast head turn, then held gaze')
    return info

def main():
    global rig
    parser=argparse.ArgumentParser();parser.add_argument('--scout',action='store_true');parser.add_argument('--timeline-only',action='store_true')
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    spec=importlib.util.spec_from_file_location('approved_chat_idle_v29',P/'build_chat_perch.py')
    rig=importlib.util.module_from_spec(spec);spec.loader.exec_module(rig)
    assert rig.CHAT_BASE_SHA==BASE_SHA
    helpers.rig=rig;helpers.scene=rig.scene
    scene=rig.scene;scene.render.fps=FPS;scene.render.threads_mode='FIXED';scene.render.threads=6
    rig.apply_pose('perch',0);provenance,provenance_sha=helpers.render_provenance()
    old=json.loads((P/'chat-perch-v26.json').read_text(encoding='utf-8'))
    assert old['baseSourceSha256']==BASE_SHA and old['renderProvenanceSha256']==provenance_sha
    # The portable seed receipt ships beside the native sources. The older
    # workstation receipt is only the initial construction fallback.
    receipt_path=P/'chat-idle-v29-seed.json'
    if not receipt_path.exists():receipt_path=WORK/'chat-perch-cache-v26.json'
    receipts=json.loads(receipt_path.read_text(encoding='utf-8'))
    assert receipts['baseSourceSha256']==BASE_SHA and receipts['renderProvenanceSha256']==provenance_sha
    seed=receipts['states'];cache={};verified=set()
    destination=P/'chat-idle-frames-v29';destination.mkdir(exist_ok=True)
    metadata={k:old[k] for k in ['baseSourceSha256','frameWidth','frameHeight','columns','fps','renderProvenanceSha256',
                               'defaultHeading','perchHeading','startHeading','frontHeading','camera','contactDescription']}
    metadata.update(version=29,dependencies=['build_chat_idle_v29.py','build_chat_perch_v26.py','build_chat_perch.py','build_raven.py'],
                    temporalEvaluation='Only idle head/neck turns run at 2x speed. Same 25-second cycle, 5-second target cadence, turn onsets, breathing and blink clocks. Exact native geometry/render-provenance aliases reuse pixels.',
                    headTurnTiming={'turnStartsSeconds':[TURN_START+5*i for i in range(5)],'previousDurationSeconds':OLD_TURN_SECONDS,
                                    'durationSeconds':TURN_SECONDS,'speedMultiplier':2,'headTargets':GAZES},clips={})
    fresh=0;reused=0;seen=set();frame=0
    for clip,count in COUNTS.items():
        item={'frames':count,'fps':FPS,'duration':count/FPS,'loop':True,'startFrame':frame+1,'poses':[],
              'inspection':[{'frame':f,'label':clip+' '+str(f)} for f in INSPECTION[clip]],
              'sourcePattern':'chat-idle-frames-v29/'+clip+'-%04d.png'}
        if clip=='idle':item.update(pauseSeconds=[4.5,9.5,14.5,19.5,24.5],pauseFrames=[270,570,870,1170,1470],headTurnTiming=metadata['headTurnTiming'])
        for index in range(count):
            frame+=1;scene.frame_set(frame);info=apply_pose(clip,index);pose=rig.pose_metadata(info)
            key=helpers.geometry_digest();pose['evaluatedGeometrySha256']=key;item['poses'].append(pose);seen.add(key)
            if not args.timeline_only and (not args.scout or index in INSPECTION[clip]):
                path=destination/f'{clip}-{index:04d}.png';cached=cache.get(key) or seed.get(key)
                if cached:
                    source=Path(cached['path'])
                    if not source.is_absolute():source=P/source
                    if str(source) not in verified:
                        assert source.exists() and hashlib.sha256(source.read_bytes()).hexdigest()==cached['pngSha256'],str(source)
                        verified.add(str(source))
                    if source.resolve()!=path.resolve():shutil.copyfile(source,path)
                    reused+=1
                else:
                    scene.render.filepath=str(path);bpy.ops.render.render(write_still=True);fresh+=1
                    cache[key]={'path':str(path),'pngSha256':hashlib.sha256(path.read_bytes()).hexdigest(),'origin':'v29'}
                if index%50==0 or not cached:print('CHAT_IDLE_V29',clip,index+1,'/',count,'fresh',fresh,'reused',reused,flush=True)
        metadata['clips'][clip]=item
    metadata.update(evaluatedUniquePoses=len(seen),freshNativeRenders=fresh,reusedExactCells=reused)
    WORK.mkdir(exist_ok=True)
    (WORK/'chat-idle-v29-provenance.json').write_text(json.dumps(provenance,indent=2),encoding='utf-8')
    if args.scout:
        (WORK/'chat-idle-v29-scout.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    else:
        # Bake every native 60 fps sample with the approved compact shape bank.
        helpers.apply_pose=apply_pose
        helpers.bake_timeline(metadata,WORK/'raven-chat-idle-v29-native-intermediate.blend')
        scene['README']='v29 idle only: 25-second loop with the same five gaze targets and 4.625 + n*5 s turn onsets. Head/neck reaches the next target in 0.1875 s (2x faster), then holds. Body breathing, blinks and Send-button claw grip remain at the accepted timing.'
        scene['Head turn speed multiplier']=2
        scene['Head turn seconds']=TURN_SECONDS
        bpy.ops.wm.save_as_mainfile(filepath=str(P/'raven-chat-idle-v29.blend'))
        (P/'chat-idle-native-v29.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    (WORK/'chat-idle-v29-render-checks.json').write_text(json.dumps({'version':29,'freshNativeRenders':fresh,'reusedExactCells':reused,
                 'logicalFrames':frame,'uniqueGeometry':len(seen),'renderProvenanceSha256':provenance_sha,'scout':args.scout},indent=2),encoding='utf-8')
    print('CHAT_IDLE_V29_COMPLETE',frame,'logical frames;',fresh,'fresh renders;',reused,'exact geometry aliases',flush=True)

if __name__=='__main__':main()
