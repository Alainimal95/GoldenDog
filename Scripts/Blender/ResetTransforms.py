#reset transforms
import bpy

#capture selection
sel = bpy.context.selected_objects

#reset all transforms for selection
for s in sel:
    s.location = (0,0,0)
    s.rotation_euler = (0,0,0)
    s.scale = (1,1,1)