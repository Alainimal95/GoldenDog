"""
Group Snap - Blender 5.0.1

Select a group of objects, run the operator, then:
  1. Click a vertex to set the REFERENCE point.
  2. Click a vertex to set the DESTINATION point.
The selected objects are translated by (destination - reference).

ESC / Right-click cancels at any point.

Run this in Blender's Text Editor (Alt+P), then either:
  - call bpy.ops.object.group_snap('INVOKE_DEFAULT') from the
    Python console, or
  - use the small test panel added under View3D > Sidebar > "Snap Tool".

Later, drop OBJECT_OT_group_snap straight into your addon module.
"""

import bpy
import gpu
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader


# ---------------------------------------------------------------------------
# BVH cache: build once per operator run, reused every mouse move.
# ---------------------------------------------------------------------------

def build_bvh_cache(context):
    """Build a world-space BVH tree per visible mesh object.

    Returns: dict[obj_name] = {
        'bvh': BVHTree,
        'verts_world': [Vector, ...],
        'tris': [(i0, i1, i2), ...],   # matches BVH triangle indices
    }
    """
    depsgraph = context.evaluated_depsgraph_get()
    cache = {}

    for obj in context.visible_objects:
        if obj.type != 'MESH':
            continue

        obj_eval = obj.evaluated_get(depsgraph)
        mesh = obj_eval.to_mesh()
        if mesh is None or len(mesh.vertices) == 0:
            if mesh is not None:
                obj_eval.to_mesh_clear()
            continue

        mesh.calc_loop_triangles()
        mat = obj.matrix_world.copy()

        verts_world = [mat @ v.co for v in mesh.vertices]
        tris = [tuple(tri.vertices) for tri in mesh.loop_triangles]

        if tris:
            bvh = BVHTree.FromPolygons(verts_world, tris)
            cache[obj.name] = {
                'bvh': bvh,
                'verts_world': verts_world,
                'tris': tris,
            }

        obj_eval.to_mesh_clear()

    return cache


def raycast_nearest_vertex(context, event, cache):
    """Cast a ray from the mouse through the scene, return the world-space
    position of the nearest vertex on the closest hit triangle, or None."""
    region = context.region
    rv3d = context.region_data
    coord = (event.mouse_region_x, event.mouse_region_y)

    ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
    ray_dir = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)

    best_point = None
    best_dist = None

    for entry in cache.values():
        loc, _normal, tri_index, dist = entry['bvh'].ray_cast(ray_origin, ray_dir)
        if loc is None:
            continue
        if best_dist is not None and dist >= best_dist:
            continue

        tri = entry['tris'][tri_index]
        verts = entry['verts_world']
        nearest_v = min((verts[i] for i in tri), key=lambda v: (v - loc).length_squared)

        best_dist = dist
        best_point = nearest_v

    return best_point


# ---------------------------------------------------------------------------
# Viewport feedback (small crosshair at ref / hover points)
# ---------------------------------------------------------------------------

_shader = None


def get_shader():
    global _shader
    if _shader is None:
        _shader = gpu.shader.from_builtin('FLAT_COLOR')
    return _shader


def draw_callback(op, context):
    points = []
    colors = []
    size = 0.06  # world-space half-length of the crosshair arms

    def add_cross(p, color):
        for axis in range(3):
            offset = Vector((0.0, 0.0, 0.0))
            offset[axis] = size
            points.append(p - offset)
            points.append(p + offset)
            colors.append(color)
            colors.append(color)

    GREEN = (0.0, 1.0, 0.2, 1.0)
    CYAN = (0.0, 1.0, 1.0, 1.0)
    YELLOW = (1.0, 0.9, 0.0, 1.0)

    if op.ref_point is not None:
        add_cross(op.ref_point, GREEN)

    if op.current_hover is not None:
        hover_color = YELLOW if op.state == 'DESTINATION' else CYAN
        add_cross(op.current_hover, hover_color)

    if not points:
        return

    shader = get_shader()
    batch = batch_for_shader(shader, 'LINES', {"pos": points, "color": colors})

    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE')
    gpu.state.line_width_set(3.0)

    shader.bind()
    batch.draw(shader)

    gpu.state.line_width_set(1.0)
    gpu.state.depth_test_set('LESS_EQUAL')
    gpu.state.blend_set('NONE')


# ---------------------------------------------------------------------------
# Operator
# ---------------------------------------------------------------------------

class OBJECT_OT_group_snap(bpy.types.Operator):
    """Translate the selected objects so a reference point lands on a destination point"""
    bl_idname = "object.group_snap"
    bl_label = "Group Snap"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and context.selected_objects

    def invoke(self, context, event):
        self.selected_objects = list(context.selected_objects)
        if not self.selected_objects:
            self.report({'WARNING'}, "No objects selected")
            return {'CANCELLED'}

        self.cache = build_bvh_cache(context)
        self.state = 'REFERENCE'      # then 'DESTINATION'
        self.ref_point = None
        self.dest_point = None
        self.current_hover = None

        self.draw_handler = bpy.types.SpaceView3D.draw_handler_add(
            draw_callback, (self, context), 'WINDOW', 'POST_VIEW'
        )

        context.window_manager.modal_handler_add(self)
        context.area.header_text_set("Click a vertex for the REFERENCE point  |  Esc to cancel")
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        context.area.tag_redraw()

        if event.type == 'MOUSEMOVE':
            self.current_hover = raycast_nearest_vertex(context, event, self.cache)
            return {'RUNNING_MODAL'}

        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            hit = raycast_nearest_vertex(context, event, self.cache)
            if hit is None:
                self.report({'WARNING'}, "No surface/vertex under cursor")
                return {'RUNNING_MODAL'}

            if self.state == 'REFERENCE':
                self.ref_point = hit
                self.state = 'DESTINATION'
                context.area.header_text_set("Click a vertex for the DESTINATION point  |  Esc to cancel")
            else:
                self.dest_point = hit
                self.apply_translation()
                self.finish(context)
                return {'FINISHED'}
            return {'RUNNING_MODAL'}

        if event.type in {'RIGHTMOUSE', 'ESC'}:
            self.finish(context)
            self.report({'INFO'}, "Snap cancelled")
            return {'CANCELLED'}

        # Let everything else (orbit, pan, zoom, numpad views) pass through.
        return {'PASS_THROUGH'}

    def finish(self, context):
        bpy.types.SpaceView3D.draw_handler_remove(self.draw_handler, 'WINDOW')
        context.area.header_text_set(None)

    def apply_translation(self):
        delta = self.dest_point - self.ref_point
        for obj in self.selected_objects:
            obj.location += delta
        self.report({'INFO'}, f"Moved {len(self.selected_objects)} object(s) by {tuple(round(c, 4) for c in delta)}")


# ---------------------------------------------------------------------------
# Minimal test panel 
# ---------------------------------------------------------------------------

class VIEW3D_PT_snap_group_test(bpy.types.Panel):
    bl_label = "Snap Tool"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Snap Tool"

    def draw(self, context):
        layout = self.layout
        layout.operator("object.group_snap", icon='SNAP_VERTEX')


classes = (
    OBJECT_OT_group_snap,
    VIEW3D_PT_snap_group_test,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()