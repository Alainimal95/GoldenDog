#originToBase
#objects assumed to be at origin, transforms at default

import bpy

#capture selection
sel = bpy.context.selected_objects

#find lowest point
for s in sel:
    
    #get bbox ptmin z location
    corners = s.bound_box
    low = min(c[2] for c in corners)
     
    #transform up by abs of that amnt
    s.location.z += abs(low)
    
#apply transforms
bpy.ops.object.transform_apply(location=True)