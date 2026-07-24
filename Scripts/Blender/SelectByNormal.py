# make a face selection of faces whose normals match a user defined direction
import bpy
import bmesh
import bl_math
from mathutils import Vector

# ---------------------------------------------------------------------------
# helper functions
# ---------------------------------------------------------------------------

# get vector of target direction
def get_axis(dir):
    #set enum property 
    axis_vector = [
        (1, 0, 0),
        (-1, 0, 0),
        (0, 1, 0),
        (0, -1, 0),
        (0, 0, 1),
        (0, 0, -1)
    ]
    return axis_vector[dir]

# select faces with matching normals
def select_by_normal(dir, threshold, extend):
    # TODO:
        # add mode switch here
        # add invert selection bool
    target_vector = get_axis(dir)
    
    # bmesh faces of object
    act = bpy.context.active_object
    bm = bmesh.from_edit_mesh(act.data)
    faces = bm.faces
    
    # TODO: soft select the target vector
    if not extend:
        for f in faces:
            f.select = 0 
    sel = [n for n in faces if Vector.dot(n.normal, target_vector) >= threshold]
    for s in sel:
        s.select = 1
    
    # update viewport
    bmesh.update_edit_mesh(act.data)

def remap_value_range(value, in_min, in_max, out_min, out_max, clamp_in, clamp_out):
    # remaps a value from its input range to its output range
    # TODO: add clamps of inputs/outputs
    
    # get the difference of each range min & max, range scales, and the offset
    in_rng = in_max - in_min
    out_rng = out_max - out_min
    scale = in_rng/out_rng
    offset = out_min - in_min
    
    """
    # debug print
    print("in value: ", value)
    print("in min: ", in_min)
    print("in max: ", in_max)
    print("out min: ", out_min)
    print("out max: ", out_max)
    print("in range: ", in_rng)
    print("out range: ", out_rng)
    print("scale: ", scale)
    print("offset: ", offset)
    """
    
    # clamp input
    if clamp_in:
        # clamp, but ensure clamp mins/maxes are not flipped
        clamp_min = min(in_min, in_max)
        clamp_max = max(in_min, in_max)
        value = bl_math.clamp(value, clamp_min, clamp_max)
        
        # debug print
        # print("in clamped: ", value)
    
    # remap value
    value = (value/scale) + offset 
    
    # debug print remapped value
    # print("out value: ", value)
    
    # clamp output
    if clamp_out:
        # clamp, but ensure clamp mins/maxes are not flipped
        clamp_min = min(out_min, out_max)
        clamp_max = max(out_min, out_max)
        value = bl_math.clamp(value, clamp_min, clamp_max)
        
        # debug print
        # print("out clamped: ", value)
    
    return value
    
#
# operator
#

class NRM_OT_select_by_normal(bpy.types.Operator):
    """Select faces of an object whose normals are aligned to a direction"""
    bl_label = "Select By Normal"
    bl_idname = "nrm.select_by_normal"
    bl_options = {'REGISTER', 'UNDO'}
    
    directions = [
        ("0", "X+", ""),
        ("1", "X-", ""),
        ("2", "Y+", ""),
        ("3", "Y-", ""),
        ("4", "Z+", ""),
        ("5", "Z-", "")
    ]
    
    # options and layout
    axis: bpy.props.EnumProperty(name="Axis", items=directions)
    threshold: bpy.props.FloatProperty(name="Threshold (Cone) Angle", default=0)
    extend: bpy.props.BoolProperty(name="Extend Selection", default=True)
    
    @classmethod
    def poll(cls, context):
        return (
            bpy.context.active_object
            #and context.mode == 'EDIT'
        )
        
    def execute(self, context):
        
        dir = int(self.axis)
        extend = self.extend
        #remap threshold from 0, 180 to 1, -1  
        threshold = remap_value_range(self.threshold, 0, 180, 1, -1, True, True)
        print(extend)
        
        try:
            select_by_normal(dir, threshold, extend)
        except ValueError as e:
            self.report({'WARNING'}, str(e))
            return {'CANCELLED'}        
        return {'FINISHED'}
    
    def invoke(self, context, event):
        
        return context.window_manager.invoke_props_dialog(self)


# ---------------------------------------------------------------------------
# register
# ---------------------------------------------------------------------------

classes = (
    NRM_OT_select_by_normal,   
)

scene = bpy.types.Scene

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
"""
    # user input scene props
    
    # create enum items
    directions = [
        ("X+", "X+", "", 0),
        ("X-", "X-", "", 1),
        ("Y+", "Y+", "", 2),
        ("Y-", "Y-", "", 3),
        ("Z+", "Z+", "", 4),
        ("Z-", "Z-", "", 5)
    ]
    scene.axis = bpy.props.EnumProperty(items=directions)
"""    
    # mode selector
"""
    modes = [
        ("AXIS", "Axis", "", 0),
        ("ACTIVE", "Active", "", 1),
        ("SELECTION", "Selection", "", 2)
    ]
    scene.nrm_select_mode = bpy.props.EnumProperty(items=modes)
"""

def unregister():
    # del scene.axis

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
        

if __name__ == "__main__":
    register()

    # Test call.
    bpy.ops.nrm.select_by_normal('INVOKE_DEFAULT')