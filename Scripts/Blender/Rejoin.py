# Merge the verts of each selected object, then combine them under the active object
import bpy
"""
if obj.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
"""
# capture original selection
view_layer = bpy.context.view_layer
orig_act = view_layer.objects.active
orig_sel = list(bpy.context.selected_objects)
        
for s in orig_sel:
    # clear selection select current
    bpy.ops.object.select_all(action='DESELECT')
    s.select_set(True)
    
    # enter edit mode, select all verts
    bpy.ops.object.mode_set(mode = 'EDIT')
    bpy.ops.mesh.select_mode(type="VERT")
    bpy.ops.mesh.select_all(action='SELECT')
    
    # merge verts and return to object mode
    bpy.ops.mesh.remove_doubles()
    bpy.ops.object.mode_set(mode='OBJECT')
    
# combine objs under original active
bpy.ops.object.select_all(action='DESELECT')
for o in original_selected:
    o.select_set(True)
view_layer.objects.active = orig_act
bpy.ops.object.join()