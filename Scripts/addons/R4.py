bl_info = {
    "name": "R4: Rejoin, Restore, Reset, Recenter",
    "author": "You",
    "version": (1, 0, 1),
    "blender": (5, 0, 1),
    "location": "View3D > Sidebar > R4",
    "description": "Merge verts/objects, restore rotation, reset transforms, and recenter origin at base",
    "category": "Object",
}

import bpy
import bmesh
import math
from mathutils import Vector, Matrix


# ---------------------------------------------------------------------------
# Core math / mesh-reading helpers
# ---------------------------------------------------------------------------

# convert normal to world space
def _normal_to_world(obj, local_normal):
    normal_matrix = obj.matrix_world.to_3x3().inverted_safe().transposed()
    return (normal_matrix @ local_normal).normalized()

# use selected geometry to capture a vector (approach dependant on selection type)
def get_vector_from_selection(obj):
    #Read the current edit mode selection -> normalized world-space vector
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

#reconstruct the rotation
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

#restore rotation values using a parent empty to null current orientation
def restore_rotation(obj, priority='FORWARD'):
    #read custom properties and build the rot matrix
    forward = Vector(obj["r4_forward"])
    up = Vector(obj["r4_up"])
    rot_matrix = build_rotation_matrix(forward, up, priority=priority)
    
    #return to object mode
    if obj.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

    if obj.data.users > 1:
        obj.data = obj.data.copy()
    
    #get selected and active objects
    view_layer = bpy.context.view_layer
    original_active = view_layer.objects.active
    original_selected = list(bpy.context.selected_objects)
    
    #add and align empty (will become parent)
    empty = bpy.data.objects.new("R4_TEMP_EMPTY", None)
    bpy.context.collection.objects.link(empty)
    empty.matrix_world = Matrix.Translation(obj.matrix_world.translation) @ rot_matrix
    
    #clear selection, make empty parent of obj
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    empty.select_set(True)
    view_layer.objects.active = empty
    bpy.ops.object.parent_set(type='OBJECT', keep_transform=True)
    
    #zero out rotation on empty
    empty.rotation_euler = (0.0, 0.0, 0.0)
    
    #select target obj only 
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    view_layer.objects.active = obj
    
    #unparent(keep), apply xforms, rotate back to position
    bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')    
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)
    obj.rotation_euler = rot_matrix.to_euler(obj.rotation_mode)

    #remove empty/custom properties and restore selection
    bpy.data.objects.remove(empty, do_unlink=True)
    del obj["r4_forward"]
    del obj["r4_up"]
    
    bpy.ops.object.select_all(action='DESELECT')
    for o in original_selected:
        o.select_set(True)
    view_layer.objects.active = original_active


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

#define forward vector
class R4_OT_set_forward(bpy.types.Operator):
    bl_idname = "r4.set_forward"
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
        obj["r4_forward"] = tuple(v)
        self.report({'INFO'}, f"Forward vector set: ({v.x:.3f}, {v.y:.3f}, {v.z:.3f})")
        return {'FINISHED'}

#define up vector
class R4_OT_set_up(bpy.types.Operator):
    bl_idname = "r4.set_up"
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
        obj["r4_up"] = tuple(v)
        self.report({'INFO'}, f"Up vector set: ({v.x:.3f}, {v.y:.3f}, {v.z:.3f})")
        return {'FINISHED'}

#clear captured vectors
class R4_OT_clear_vectors(bpy.types.Operator):
    bl_idname = "r4.clear_vectors"
    bl_label = "Clear Stored Vectors"
    bl_description = "Discard the stored Forward/Up vectors on this object"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and ("r4_forward" in obj or "r4_up" in obj)

    def execute(self, context):
        obj = context.object
        obj.pop("r4_forward", None)
        obj.pop("r4_up", None)
        return {'FINISHED'}

#restore rotation
class R4_OT_restore_rotation(bpy.types.Operator):
    bl_idname = "r4.restore_rotation"
    bl_label = "Restore Rotation"
    bl_description = "Reconstruct the object's rotation from the stored Forward/Up vectors"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.object
        return (
            obj is not None
            and obj.type == 'MESH'
            and "r4_forward" in obj
            and "r4_up" in obj
        )

    def execute(self, context):
        obj = context.object
        priority = context.scene.r4_priority
        try:
            restore_rotation(obj, priority=priority)
        except (RuntimeError, ValueError) as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        self.report({'INFO'}, f"Rotation restored on '{obj.name}'")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------

class R4_PT_panel(bpy.types.Panel):
    bl_label = "R4: Rejoin, Restore, Reset, Recenter"
    bl_idname = "R4_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "R4"

    def draw(self, context):
        layout = self.layout
        obj = context.object

        if obj is None or obj.type != 'MESH':
            layout.label(text="Select a mesh object", icon='INFO')
            return

        layout.label(text="Restore Rotation", icon='ORIENTATION_GIMBAL')

        fwd = obj.get("r4_forward")
        up = obj.get("r4_up")

        box = layout.box()
        box.label(text="1. Forward Vector (+Y)")
        box.operator("r4.set_forward", icon='EMPTY_SINGLE_ARROW')
        if fwd:
            box.label(text=f"({fwd[0]:.3f}, {fwd[1]:.3f}, {fwd[2]:.3f})")
        else:
            box.label(text="Not set", icon='DOT')

        box = layout.box()
        box.label(text="2. Up Vector (+Z)")
        box.operator("r4.set_up", icon='EMPTY_SINGLE_ARROW')
        if up:
            box.label(text=f"({up[0]:.3f}, {up[1]:.3f}, {up[2]:.3f})")
        else:
            box.label(text="Not set", icon='DOT')

        layout.separator()
        layout.label(text="Priority if not perpendicular:")
        layout.prop(context.scene, "r4_priority", expand=True)

        layout.separator()
        layout.operator("r4.restore_rotation", icon='ORIENTATION_GIMBAL')
        layout.operator("r4.clear_vectors", icon='TRASH')


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

classes = (
    R4_OT_set_forward,
    R4_OT_set_up,
    R4_OT_clear_vectors,
    R4_OT_restore_rotation,
    R4_PT_panel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.r4_priority = bpy.props.EnumProperty(
        name="Priority",
        description="Which vector stays exact when Forward and Up aren't perpendicular",
        items=[
            ('FORWARD', "Forward", "Keep Forward exact, recompute Up"),
            ('UP', "Up", "Keep Up exact, recompute Forward"),
        ],
        default='FORWARD',
    )


def unregister():
    del bpy.types.Scene.r4_priority

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
