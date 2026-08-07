bl_info = {
    "name": "Select By Normal",
    "author": "Hypernova",
    "version": (1, 5, 1),
    "blender": (5, 0, 1),
    "location": "View3D > Edit Mesh > Select",
    "description": "Select any mesh elements by alignment to a direction, optional limits by connectivity and selection",
    "category": "Mesh",
}
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
    # read the current edit mode selection -> normalized world-space vector
    act = bpy.context.active_object
    bm = bmesh.from_edit_mesh(act.data)
    
    # average the selection of verts 
    bm.verts.ensure_lookup_table()
    
    # active component normal handling
    active_component = bm.select_history.active
    select_mode = bpy.context.scene.tool_settings.mesh_select_mode
    
    # if in edge select mode, get the verts of the selected edge(s)
    if select_mode[1]:
        sel_verts = [v for e in bm.edges if e.select for v in e.verts]
    else:
        sel_verts = [v for v in bm.verts if v.select]
       
    vert_normals = [v.normal for v in sel_verts]
    avg_norm = sum(vert_normals, Vector()) / len(vert_normals)
    
    # if in edge select mode, use vert normal averages
    if select_mode[1]: 
        active_normal = avg_norm
    else:
        active_normal = active_component.normal
    
    # set enum property 
    axis_vector = [
        active_normal,    # active
        avg_norm,    # selected
        (1, 0, 0),
        (-1, 0, 0),
        (0, 1, 0),
        (0, -1, 0),
        (0, 0, 1),
        (0, 0, -1)
    ]
    return axis_vector[dir]

def get_connected(source, mode):
    """
    mode: 'VERT', 'EDGE', or 'FACE'
    source: one or more elements matching mode
    Returns a set of bmesh elements of the requested type.
    """
    if hasattr(source, '__iter__'):
        source = list(source)
    else:
        source = [source]

    visited = set(source)
    stack = list(source)

    while stack:
        elem = stack.pop()

        if mode == 'VERT':
            neighbors = [e.other_vert(elem) for e in elem.link_edges]

        elif mode == 'EDGE':
            neighbors = [e for v in elem.verts for e in v.link_edges if e is not elem]

        elif mode == 'FACE':
            neighbors = [f for e in elem.edges for f in e.link_faces if f is not elem]

        else:
            raise ValueError(f"Unknown mode: {mode}")

        for n in neighbors:
            if n not in visited:
                visited.add(n)
                stack.append(n)

    return visited


# select mesh elements with matching normals
def select_by_normal(dir, threshold, extend, deselect, limit_selected, limit_connected):
    context = bpy.context
    # get target vector
    target_vector = get_axis(dir)

    # bmesh elements of object
    act = context.active_object
    bm = bmesh.from_edit_mesh(act.data)
    mode = bm.select_mode
    
    # switch selection checking to correct mode 
    if mode != {'FACE'}:
        # ensure vert selection mode active in case of edges
        context.tool_settings.mesh_select_mode = (True, False, False)
        bmesh.update_edit_mesh(act.data)
        
        # set verts as the elements to search/select
        elements = bm.verts
        connect_mode = 'VERT'
    
    else:
        # set faces as the elements to search/select
        elements = bm.faces
        connect_mode = 'Face'

    # limit to selected
    sel = [s for s in elements if s.select == True]
    
    # limit to connected
    connected = get_connected(sel, connect_mode)
    
    # if enabled, include components from original selection
    if not extend:
        for e in elements:
            e.select = False
    
    # select if within threshold angle
    matching = [m for m in elements if Vector.dot(m.normal, target_vector) >= threshold and
        (m in sel or limit_selected == False) and
        (m in connected or limit_connected == False)
        ]
    
    # select or deselect elements matching the target vector/threshold
    if deselect:
        for m in matching:
            m.select = False
    else:
        for m in matching:
            m.select = True    
    
    # flush selection and update viewport - swap back to edge select mode if applicable
    bm.select_flush_mode()
    if mode == {'EDGE'}:
        context.tool_settings.mesh_select_mode = (False, True, False)
    bmesh.update_edit_mesh(act.data)

def remap_value_range(value, in_min, in_max, out_min, out_max, clamp_in, clamp_out):
    # remaps a value from its input range to its output range
    
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
        ("0", "Active", ""),
        ("1", "Selected", ""),
        ("2", "X+", ""),
        ("3", "X-", ""),
        ("4", "Y+", ""),
        ("5", "Y-", ""),
        ("6", "Z+", ""),
        ("7", "Z-", "")
    ]
    
    # options and layout
    axis: bpy.props.EnumProperty(name="Axis", items=directions)
    threshold: bpy.props.FloatProperty(name="Threshold (Cone) Angle", default=0)
    extend: bpy.props.BoolProperty(name="Extend Selection", default=False)
    deselect: bpy.props.BoolProperty(name="Deselect", default=False)
    limit_selected: bpy.props.BoolProperty(name="Selected Only", default=False)
    limit_connected: bpy.props.BoolProperty(name="Connected Only", default=False)
        
    @classmethod
    def poll(cls, context):
        return (
            bpy.context.active_object
            # and context.mode == 'EDIT'
        )
        
    def execute(self, context):
        
        dir = int(self.axis)
        # remap threshold from 0, 180 to 1, -1  
        threshold = remap_value_range(self.threshold, 0, 180, 1, -1, True, True)
        extend = self.extend
        deselect = self.deselect
        limit_selected = self.limit_selected
        limit_connected = self.limit_connected
        
        try:
            select_by_normal(dir, threshold, extend, deselect, limit_selected, limit_connected)
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

def draw_menu(self, context):
    layout = self.layout
    layout.separator
    layout.operator(NRM_OT_select_by_normal.bl_idname)
    
def register():
    
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.VIEW3D_MT_select_edit_mesh.append(draw_menu)

def unregister():

    bpy.types.VIEW3D_MT_select_edit_mesh.remove(draw_menu)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
        

if __name__ == "__main__":
    register()

    # Test call.
    # bpy.ops.nrm.select_by_normal('INVOKE_DEFAULT')