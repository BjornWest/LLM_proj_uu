"""Common neutral junction for independent v27 flight modules.

Execute after the frozen build_chat_flight.py live-rig prefix. This helper
never edits the accepted model, camera or earlier rendered animation assets.
The neutral pose is v26 patrol phase zero with root bank removed before the
connected flight legs are evaluated. All new flight modules share it exactly.
"""

def neutral_flight_junction():
    global body_coordinates,contact_point,native_root_delta
    for owner,part,key in leg_paths:key.value=0
    for mesh,key in wing_strokes:key.value=0
    for key in grips:key.value=0
    contact_point=None;native_root_delta=Vector()
    pose('soaring',0)
    localize()
    # Phase zero has a -0.32 rad course bank. Retain its heading, but a
    # straight soaring junction should meet the next module without tilt.
    root.rotation_euler=(0,0,root.rotation_euler.z)
    tail.rotation_euler.y+=.055
    inherited_wings('patrol',0)
    body_coordinates=shared_flight_body(1)
    # Evaluate the connected hip/knee/ankle chain after leveling the root.
    shared_flight_legs(0)
    return body_coordinates
