bl_info = {
    "name": "Port64",
    "author": "Hypernova",
    "version": (1, 1, 0),
    "blender": (5, 0, 1),
    "location": "View3D > Sidebar > Port64",
    "description": "Toolset for processing assets imported from project 64",
    "category": "Object",
}

import bpy
import os
import gpu
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

#
# group snap
#

# BVH cache: build once per operator run, reused every mouse move
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

# viewport feedback (small crosshair at ref / hover points)
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
    

#
# consolidate/designate materials
#

# get slot 0 material
"""
TODO: may have to add search functionality here if
used on objs with multiple mat slots.
For now, this is not the intended use
"""
def get_mtl(obj):
    if not obj.material_slots:
        return None
    return obj.material_slots[0].material

# check texture file
def get_tex(obj):
    mtl = get_mtl(obj)
    if mtl is None or not mtl.use_nodes or mtl.node_tree is None:
        return None

    # get texture node from tree (first material slot)
    tex = [n for n in mtl.node_tree.nodes if n.type == 'TEX_IMAGE']
    if not tex:
        return None
    return tex[0].image

# identify a texture by its source filename rather than by datablock identity,
# so duplicate Image datablocks pointing at the same file (e.g. "tex.001")
# still count as a match. Falls back to the datablock name if there's no
# filepath (e.g. generated/packed images with no source file).
def get_tex_key(image):
    if image is None:
        return None
    if image.filepath:
        return os.path.basename(bpy.path.abspath(image.filepath)).lower()
    return image.name

# consolidate

#TODO: add func to override which mat is being assigned to all objs
def find_matching_objects(context):
    """Find the other selected meshes that share the active object's source
    texture (matched by filename, not by Image datablock identity).

    Returns (active, active_mtl, matches). Raises ValueError with a
    user-facing message if the active object can't be used as the source.
    """
    # capture active and passive selected objects
    sel = context.selected_objects
    active = context.active_object

    if active is None:
        raise ValueError("No active object")

    passive = [s for s in sel if s != active and s.type == 'MESH']
    if not passive:
        raise ValueError("Select at least one other mesh besides the active object")

    # get active object's material
    active_mtl = get_mtl(active)
    if active_mtl is None:
        raise ValueError(f"'{active.name}' has no material in slot 0")

    # get active object's texture
    active_tex = get_tex(active)
    if active_tex is None:
        raise ValueError(f"Material '{active_mtl.name}' has no image texture node")

    active_key = get_tex_key(active_tex)

    # find objs in passive selection using the same texture (by filename)
    matches = [p for p in passive if get_tex_key(get_tex(p)) == active_key]

    return active, active_mtl, matches


def consolidate(context):
    """Assign the active object's material to every other selected mesh
    that shares its source texture. Returns the number of objects updated."""
    active, active_mtl, matches = find_matching_objects(context)

    for d in matches:
        d.data.materials.clear()
        d.data.materials.append(active_mtl)

    return len(matches)


def select_matching_objects(context):
    """Narrow the current selection down to the active object plus any other
    selected mesh that shares its source texture. Returns the number of
    matching objects kept (not counting the active object itself)."""
    active, _active_mtl, matches = find_matching_objects(context)
    keep = set(matches)
    keep.add(active)

    for obj in context.selected_objects:
        if obj not in keep:
            obj.select_set(False)

    context.view_layer.objects.active = active
    return len(matches)



#
# reload images
#

# find the replacement file for an image inside the texture folder.
# a same-name ".png" takes priority over the image's original extension,
# since a lot of these get re-exported to png after moving into the
# project's texture folder.
def find_matching_texture(folder, filename):
    base, ext = os.path.splitext(filename)
    png_name = base + ".png"

    search_order = [png_name] if png_name.lower() != filename.lower() else []
    search_order.append(filename)

    for name in search_order:
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            return path
    return None

# point every FILE-source image at its match in the texture folder and
# reload it. paths are stored relative to the .blend file (bpy.path.relpath)
# when the file has been saved; otherwise there's no base to be relative to,
# so we fall back to an absolute path and let the caller know.
def reload_images_from_folder(context):
    folder = bpy.path.abspath(context.scene.port64_texture_folder)
    if not folder or not os.path.isdir(folder):
        raise ValueError("Texture folder is not set or doesn't exist")

    blend_saved = bool(bpy.data.filepath)

    updated = []
    not_found = []

    for img in bpy.data.images:
        if img.source != 'FILE':
            continue  # skip generated images, render results, etc.

        current_name = os.path.basename(img.filepath) if img.filepath else img.name
        if not current_name:
            continue

        match = find_matching_texture(folder, current_name)
        if match is None:
            not_found.append(img.name)
            continue

        img.filepath = bpy.path.relpath(match) if blend_saved else match
        img.reload()
        updated.append(img.name)

    return updated, not_found, blend_saved



# ---------------------------------------------------------------------------
# operators
# ---------------------------------------------------------------------------

#
# group snap
#

class PORT64_OT_group_snap(bpy.types.Operator):
    bl_idname = "object.group_snap"
    bl_label = "Group Snap"
    bl_description = ("Click a vertex to set a reference point, then click a vertex to set "
                       "a destination. All selected objects are translated so the reference "
                       "lands on the destination")
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

#
# consolidate materials
#

class PORT64_OT_consolidate_materials(bpy.types.Operator):
    bl_idname = "object.consolidate_materials"
    bl_label = "Consolidate Materials"
    bl_description = ("Assign the active object's material to every other selected mesh "
                       "that uses the same source texture (matched by filename)")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (
            context.mode == 'OBJECT'
            and context.active_object is not None
            and len(context.selected_objects) > 1
        )

    def execute(self, context):
        try:
            count = consolidate(context)
        except ValueError as e:
            self.report({'WARNING'}, str(e))
            return {'CANCELLED'}

        if count == 0:
            self.report({'INFO'}, "No matching objects found - nothing changed")
        else:
            self.report({'INFO'}, f"Updated material on {count} object(s)")
        return {'FINISHED'}


class PORT64_OT_select_matching_textures(bpy.types.Operator):
    bl_idname = "object.port64_select_matching_textures"
    bl_label = "Select Matching Textures"
    bl_description = ("Narrow the current selection down to the active object and any "
                       "other selected mesh that uses the same source texture")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (
            context.mode == 'OBJECT'
            and context.active_object is not None
            and len(context.selected_objects) > 1
        )

    def execute(self, context):
        try:
            count = select_matching_objects(context)
        except ValueError as e:
            self.report({'WARNING'}, str(e))
            return {'CANCELLED'}

        self.report({'INFO'}, f"Kept {count} matching object(s) selected, plus the active object")
        return {'FINISHED'}

#
# reload images
#

class PORT64_OT_reload_images(bpy.types.Operator):
    bl_idname = "image.port64_reload_images"
    bl_label = "Reload Images From Folder"
    bl_description = ("Search the texture folder for a file matching each image's current "
                       "filename (preferring a same-named .png) and reload it from there")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(context.scene.port64_texture_folder)

    def execute(self, context):
        try:
            updated, not_found, blend_saved = reload_images_from_folder(context)
        except ValueError as e:
            self.report({'WARNING'}, str(e))
            return {'CANCELLED'}

        if not updated:
            self.report({'WARNING'}, "No matching images found in texture folder")
            return {'FINISHED'}

        msg = f"Reloaded {len(updated)} image(s)"
        if not_found:
            msg += f", {len(not_found)} not found"
        if not blend_saved:
            msg += " (paths stored as absolute - save the .blend to enable relative paths)"
        self.report({'INFO'}, msg)
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# panel
# ---------------------------------------------------------------------------

class PORT64_PT_panel(bpy.types.Panel):
    bl_label = "Port64"
    bl_idname = "PORT64_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Port64"

    def draw(self, context):
        layout = self.layout

        col = layout.column(align=True)
        col.label(text="Group Snap", icon='SNAP_VERTEX')
        col.operator(PORT64_OT_group_snap.bl_idname, text="Snap Group to Point")

        layout.separator()

        col = layout.column(align=True)
        col.label(text="Materials", icon='MATERIAL')
        col.operator(PORT64_OT_consolidate_materials.bl_idname, text="Consolidate Materials")
        col.operator(PORT64_OT_select_matching_textures.bl_idname, text="Select Matching")

        layout.separator()

        col = layout.column(align=True)
        col.label(text="Textures", icon='IMAGE_DATA')
        col.prop(context.scene, "port64_texture_folder", text="")
        col.operator(PORT64_OT_reload_images.bl_idname, text="Reload Images")

# ---------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------

classes = (
    PORT64_OT_group_snap,
    PORT64_OT_consolidate_materials,
    PORT64_OT_select_matching_textures,
    PORT64_OT_reload_images,
    PORT64_PT_panel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.port64_texture_folder = bpy.props.StringProperty(
        name="Texture Folder",
        description="Folder to search for replacement image files when reloading textures",
        subtype='DIR_PATH',
    )


def unregister():
    del bpy.types.Scene.port64_texture_folder

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()