bl_info = {
    "name": "R5: Rejoin, Restore, Reset, Recenter",
    "author": "You",
    "version": (1, 1, 1),
    "blender": (5, 0, 1),
    "location": "View3D > Sidebar > R5",
    "description": "Merge verts/objects, restore rotation, reset transforms, and recenter origin at base",
    "category": "Object",
}

import bpy
import bmesh
import math
from mathutils import Vector, Matrix


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

#
# core math / mesh-reading
#

# convert normal to world space
def _normal_to_world(obj, local_normal):
    normal_matrix = obj.matrix_world.to_3x3().inverted_safe().transposed()
    return (normal_matrix @ local_normal).normalized()

# use selected geometry to capture a vector (approach dependant on selection type)
def get_vector_from_selection(obj):
    # Read the current edit mode selection -> normalized world-space vector
    bm = bmesh.from_edit_mesh(obj.data)
    sel_faces = [f for f in bm.faces if f.select]
    sel_edges = [e for e in bm.edges if e.select]
    sel_verts = [v for v in bm.verts if v.select]

    # Checked in order of specificity (face > edge > 3-vert), since Blender's
    # selection "flush" auto-marks edges/faces selected whenever all of their
    # verts are selected
    if len(sel_faces) == 1:
        return _normal_to_world(obj, sel_faces[0].normal.copy())

    elif len(sel_edges) == 1:
        linked = sel_edges[0].link_faces
        if not linked:
            raise RuntimeError("Selected edge has no linked faces to average a normal from.")
        local_normal = Vector((0.0, 0.0, 0.0))
        for f in linked:
            local_normal += f.normal
        if local_normal.length < 1e-8:
            raise RuntimeError("Linked face normals cancelled out (edge is on a flat fold).")
        local_normal.normalize()
        return _normal_to_world(obj, local_normal)

    elif len(sel_verts) == 3:
        p1, p2, p3 = (v.co for v in sel_verts)
        local_normal = (p2 - p1).cross(p3 - p1)
        if local_normal.length < 1e-8:
            raise RuntimeError("Selected vertices are collinear; no valid normal.")
        local_normal.normalize()
        world_normal = _normal_to_world(obj, local_normal)

        world_center = obj.matrix_world @ ((p1 + p2 + p3) / 3.0)
        origin = obj.matrix_world.translation
        to_center = world_center - origin
        if to_center.length > 1e-8 and world_normal.dot(to_center) < 0:
            world_normal.negate()

        return world_normal

    raise RuntimeError(
        "Selection must be exactly one face, one edge, or three vertices "
        f"(got {len(sel_faces)} faces, {len(sel_edges)} edges, {len(sel_verts)} verts)."
    )

# reconstruct the rotation
def build_rotation_matrix(forward, up, priority='FORWARD'):
    forward = forward.normalized()
    up = up.normalized()

    right = forward.cross(up)
    if right.length < 1e-6:
        raise ValueError("Forward and Up are parallel/opposite -- cannot build a basis.")
    right.normalize()

    if priority == 'FORWARD':
        y_axis = forward
        x_axis = right
        z_axis = x_axis.cross(y_axis).normalized()
    else:
        z_axis = up
        x_axis = right
        y_axis = z_axis.cross(x_axis).normalized()

    rot3 = Matrix((
        (x_axis.x, y_axis.x, z_axis.x),
        (x_axis.y, y_axis.y, z_axis.y),
        (x_axis.z, y_axis.z, z_axis.z),
    ))
    return rot3.to_4x4()

#
# data/mesh edit
#

# rejoin (merge verts and ombine group of objs)
def rejoin():
    # capture original selection
    view_layer = bpy.context.view_layer
    orig_act = view_layer.objects.active
    orig_sel = list(bpy.context.selected_objects)
        
    for s in orig_sel:
        if s.type != 'MESH':
            continue  # skip non-mesh objects (lights, empties, cameras, etc.)

        # clear selection, select and activate current
        bpy.ops.object.select_all(action='DESELECT')
        s.select_set(True)
        view_layer.objects.active = s

        # enter edit mode, select all verts
        bpy.ops.object.mode_set(mode = 'EDIT')
        bpy.ops.mesh.select_mode(type="VERT")
        bpy.ops.mesh.select_all(action='SELECT')
    
        # merge verts and return to object mode
        bpy.ops.mesh.remove_doubles(threshold=0.0001)
        bpy.ops.object.mode_set(mode='OBJECT')
    
    # combine objs under original active
    bpy.ops.object.select_all(action='DESELECT')
    for o in orig_sel:
        if o.type == 'MESH':
            o.select_set(True)
    view_layer.objects.active = orig_act
    bpy.ops.object.join()

# recenter (origin to geometry)
def recenter_all():
    # capture original selection
    view_layer = bpy.context.view_layer
    orig_act = view_layer.objects.active
    orig_sel = list(bpy.context.selected_objects)
        
    for s in orig_sel:
        # clear selection select current
        bpy.ops.object.select_all(action='DESELECT')
        s.select_set(True)
        
        #set origin to geo
        bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY')

    # restore original selection
    bpy.ops.object.select_all(action='DESELECT')
    for o in orig_sel:
        o.select_set(True)
    view_layer.objects.active = orig_act

# restore rotation values using a parent empty to null current orientation
def restore_rotation(obj, priority='FORWARD'):
    # read custom properties and build the rot matrix
    forward = Vector(obj["R5_forward"])
    up = Vector(obj["R5_up"])
    rot_matrix = build_rotation_matrix(forward, up, priority=priority)
    
    # return to object mode
    if obj.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

    if obj.data.users > 1:
        obj.data = obj.data.copy()
    
    # get selected and active objects
    view_layer = bpy.context.view_layer
    orig_act = view_layer.objects.active
    orig_sel = list(bpy.context.selected_objects)
    
    # add and align empty (will become parent)
    empty = bpy.data.objects.new("R5_TEMP_EMPTY", None)
    bpy.context.collection.objects.link(empty)
    empty.matrix_world = Matrix.Translation(obj.matrix_world.translation) @ rot_matrix
    
    # clear selection, make empty parent of obj
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    empty.select_set(True)
    view_layer.objects.active = empty
    bpy.ops.object.parent_set(type='OBJECT', keep_transform=True)
    
    # zero out rotation on empty
    empty.rotation_euler = (0.0, 0.0, 0.0)
    
    # select target obj only 
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    view_layer.objects.active = obj
    
    # unparent(keep), apply xforms, rotate back to position
    bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')    
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)
    obj.rotation_euler = rot_matrix.to_euler(obj.rotation_mode)

    # remove empty/custom properties and restore selection
    bpy.data.objects.remove(empty, do_unlink=True)
    del obj["R5_forward"]
    del obj["R5_up"]
    
    bpy.ops.object.select_all(action='DESELECT')
    for o in orig_sel:
        o.select_set(True)
    view_layer.objects.active = orig_act

# reset all xforms
def reset_all_xforms():
    #capture selection
    sel = bpy.context.selected_objects

    #reset all transforms for selection
    for s in sel:
        s.location = (0,0,0)
        s.rotation_euler = (0,0,0)
        s.scale = (1,1,1)

# rebase (sit on ground)
def rebase():
    # capture selection
    sel = bpy.context.selected_objects

    # force an update so matrix_world/bound_box reflect any transform
    # changes made via direct property assignment just before this call
    # (e.g. reset_all_xforms) -- those don't go through an operator, so
    # without this, bound_box can still be evaluated against the OLD
    # transform, throwing the Z shift off (can even land it upside-down
    # relative to the ground plane)
    bpy.context.view_layer.update()

    # find lowest point and drop/raise each object to sit exactly on the ground
    for s in sel:
        # bound_box is in local space -- transform corners to world space
        # before comparing Z, so this still works if the object carries
        # rotation/scale (e.g. right after a Restore Rotation)
        corners_world = [s.matrix_world @ Vector(c) for c in s.bound_box]
        low = min(c.z for c in corners_world)

        # move by exactly -low: brings it up if low < 0, down if low > 0
        s.location.z -= low

        # apply requires single-user mesh data, same as restore_rotation()
        if s.data.users > 1:
            s.data = s.data.copy()

    # apply transforms
    bpy.ops.object.transform_apply(location=True)

# R5 (execute all): run the full pipeline top to bottom on one object
def run_all(obj, priority='FORWARD'):
    rejoin()
    recenter_all()
    restore_rotation(obj, priority=priority)
    reset_all_xforms()
    rebase()


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

# 
# rejoin
# 

class R5_OT_rejoin(bpy.types.Operator):
    bl_idname = "r5.rejoin"
    bl_label = "Merge And Combine"
    bl_description = "Merge vertices of all selected objects and combine with active object"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and obj.type == 'MESH' and obj.mode == 'OBJECT'

    def execute(self, context):
        #obj = context.object
        try:
            rejoin()
        except RuntimeError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        return {'FINISHED'}

# 
# recenter origin
# 

class R5_OT_recenter_all(bpy.types.Operator):
    bl_idname = "r5.recenter_all"
    bl_label = "Recenter Origin(s)"
    bl_description = "Set origins of each selected object to the geometry's center"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and obj.type == 'MESH' and obj.mode == 'OBJECT'

    def execute(self, context):
        #obj = context.object
        try:
            recenter_all()
        except RuntimeError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        return {'FINISHED'}

# 
# restore orientation
# 

# define forward vector
class R5_OT_set_forward(bpy.types.Operator):
    bl_idname = "r5.set_forward"
    bl_label = "Set Forward From Selection"
    bl_description = "Store the current edit mode selection as the forward (+Y) vector"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and obj.type == 'MESH' and obj.mode == 'EDIT'

    def execute(self, context):
        obj = context.object
        try:
            v = get_vector_from_selection(obj)
        except RuntimeError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        obj["R5_forward"] = tuple(v)
        self.report({'INFO'}, f"Forward vector set: ({v.x:.3f}, {v.y:.3f}, {v.z:.3f})")
        return {'FINISHED'}

# define up vector
class R5_OT_set_up(bpy.types.Operator):
    bl_idname = "r5.set_up"
    bl_label = "Set Up From Selection"
    bl_description = "Store the current edit mode selection as the up (+Z) vector"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and obj.type == 'MESH' and obj.mode == 'EDIT'

    def execute(self, context):
        obj = context.object
        try:
            v = get_vector_from_selection(obj)
        except RuntimeError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        obj["R5_up"] = tuple(v)
        self.report({'INFO'}, f"Up vector set: ({v.x:.3f}, {v.y:.3f}, {v.z:.3f})")
        return {'FINISHED'}

# clear captured vectors
class R5_OT_clear_vectors(bpy.types.Operator):
    bl_idname = "r5.clear_vectors"
    bl_label = "Clear Stored Vectors"
    bl_description = "Discard the stored Forward/Up vectors on this object"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and ("R5_forward" in obj or "R5_up" in obj)

    def execute(self, context):
        obj = context.object
        obj.pop("R5_forward", None)
        obj.pop("R5_up", None)
        return {'FINISHED'}

# restore rotation
class R5_OT_restore_rotation(bpy.types.Operator):
    bl_idname = "r5.restore_rotation"
    bl_label = "Restore Rotation"
    bl_description = "Reconstruct the object's rotation from the stored Forward/Up vectors"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.object
        return (
            obj is not None
            and obj.type == 'MESH'
            and "R5_forward" in obj
            and "R5_up" in obj
        )

    def execute(self, context):
        obj = context.object
        priority = context.scene.R5_priority
        try:
            restore_rotation(obj, priority=priority)
        except (RuntimeError, ValueError) as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        self.report({'INFO'}, f"Rotation restored on '{obj.name}'")
        return {'FINISHED'}

# 
# reset transforms
# 
class R5_OT_reset_xforms(bpy.types.Operator):
    bl_idname = "r5.reset_xforms"
    bl_label = "Reset All Transforms"
    bl_description = "Zero out location and rotation, then set scale to 1 on each axis"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and obj.type == 'MESH' and obj.mode == 'OBJECT'

    def execute(self, context):
        #obj = context.object
        try:
            reset_all_xforms()
        except RuntimeError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        return {'FINISHED'}

# 
# rebase
# 
class R5_OT_rebase(bpy.types.Operator):
    bl_idname = "r5.rebase"
    bl_label = "Rebase"
    bl_description = "Set the origin to the base of the geometry"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and obj.type == 'MESH' and obj.mode == 'OBJECT'

    def execute(self, context):
        #obj = context.object
        try:
            rebase()
        except RuntimeError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        return {'FINISHED'}


#
# run all
#
class R5_OT_run_all(bpy.types.Operator):
    bl_idname = "r5.run_all"
    bl_label = "Run Full Workflow"
    bl_description = (
        "Run the entire pipeline in order on the active object: Rejoin, "
        "Recenter Origin, Restore Rotation, Reset Transforms, Rebase. "
        "Requires the Forward/Up vectors to already be captured"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.object
        return (
            obj is not None
            and obj.type == 'MESH'
            and obj.mode == 'OBJECT'
            and "R5_forward" in obj
            and "R5_up" in obj
        )

    def execute(self, context):
        obj = context.object
        priority = context.scene.R5_priority
        try:
            run_all(obj, priority=priority)
        except (RuntimeError, ValueError) as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        self.report({'INFO'}, f"Full workflow completed on '{obj.name}'")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------

class R5_PT_panel(bpy.types.Panel):
    bl_label = "R5: Rejoin, Recenter, Restore, Reset, Rebase"
    bl_idname = "R5_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "R5"

    def draw(self, context):
        layout = self.layout
        obj = context.object

        if obj is None or obj.type != 'MESH':
            layout.label(text="Select a mesh object", icon='INFO')
            return

        # run everything, top to bottom
        layout.operator("r5.run_all", icon='PLAY')
        layout.separator()

        # merge and combine (rejoin)
        layout.label(text="Rejoin", icon='FULLSCREEN_EXIT')
        layout.operator("r5.rejoin", icon='FULLSCREEN_EXIT')
        
        # recenter origin
        layout.label(text="Recenter Origin", icon='LIGHTPROBE_SPHERE')
        layout.operator("r5.recenter_all", icon='LIGHTPROBE_SPHERE')
        
        # restore rotation
        layout.label(text="Restore Rotation", icon='ORIENTATION_GIMBAL')

        fwd = obj.get("R5_forward")
        up = obj.get("R5_up")

        box = layout.box()
        box.label(text="1. Forward Vector (+Y)")
        box.operator("r5.set_forward", icon='EMPTY_SINGLE_ARROW')
        if fwd:
            box.label(text=f"({fwd[0]:.3f}, {fwd[1]:.3f}, {fwd[2]:.3f})")
        else:
            box.label(text="Not set", icon='DOT')

        box = layout.box()
        box.label(text="2. Up Vector (+Z)")
        box.operator("r5.set_up", icon='EMPTY_SINGLE_ARROW')
        if up:
            box.label(text=f"({up[0]:.3f}, {up[1]:.3f}, {up[2]:.3f})")
        else:
            box.label(text="Not set", icon='DOT')

        layout.separator()
        layout.label(text="Priority if not perpendicular:")
        layout.prop(context.scene, "R5_priority", expand=True)

        layout.separator()
        layout.operator("r5.restore_rotation", icon='ORIENTATION_GIMBAL')
        layout.operator("r5.clear_vectors", icon='TRASH')
        
        # reset transforms
        layout.label(text="Reset Transforms", icon='RECOVER_LAST')
        layout.operator("r5.reset_xforms", icon='RECOVER_LAST')
        
        # rebase
        layout.label(text="Rebase", icon='IMPORT')
        layout.operator("r5.rebase", icon='IMPORT')


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

classes = (
    R5_OT_rejoin,
    R5_OT_recenter_all,
    R5_OT_set_forward,
    R5_OT_set_up,
    R5_OT_clear_vectors,
    R5_OT_restore_rotation,
    R5_OT_reset_xforms,
    R5_OT_rebase,
    R5_OT_run_all,
    R5_PT_panel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.R5_priority = bpy.props.EnumProperty(
        name="Priority",
        description="Which vector stays exact when forward and up aren't perpendicular",
        items=[
            ('FORWARD', "Forward", "Keep forward exact, recompute up"),
            ('UP', "Up", "Keep up exact, recompute forward"),
        ],
        default='FORWARD',
    )


def unregister():
    del bpy.types.Scene.R5_priority

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
