bl_info = {
    "name": "Port64",
    "author": "Hypernova",
    "version": (1, 1, 4),
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

# get material for a given slot (defaults to slot 0 for callers that don't care)
def get_mtl(obj, slot_index=0):
    slots = obj.material_slots
    if slot_index < 0 or slot_index >= len(slots):
        return None
    return slots[slot_index].material

# check texture file for a given slot
def get_tex(obj, slot_index=0):
    mtl = get_mtl(obj, slot_index)
    if mtl is None or not mtl.use_nodes or mtl.node_tree is None:
        return None

    # get texture node from tree
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

def find_matching_objects(context):
    """Find the other selected meshes that share the SOURCE texture of the
    active object's chosen material slot (matched by filename, not by Image
    datablock identity). The slot index (context.scene.port64_material_slot_index)
    only applies to the active object - target objects are assumed to use a
    single material slot, so their texture is always read from slot 0.

    Returns (active, active_mtl, matches). Raises ValueError with a
    user-facing message if the active object can't be used as the source.
    """
    slot_index = context.scene.port64_material_slot_index

    # capture active and passive selected objects
    sel = context.selected_objects
    active = context.active_object

    if active is None:
        raise ValueError("No active object")

    passive = [s for s in sel if s != active and s.type == 'MESH']
    if not passive:
        raise ValueError("Select at least one other mesh besides the active object")

    # get active object's material in the chosen source slot
    active_mtl = get_mtl(active, slot_index)
    if active_mtl is None:
        raise ValueError(f"'{active.name}' has no material in slot {slot_index}")

    # get active object's texture in that same slot
    active_tex = get_tex(active, slot_index)
    if active_tex is None:
        raise ValueError(f"Material '{active_mtl.name}' has no image texture node")

    active_key = get_tex_key(active_tex)

    # find objs in passive selection using the same texture (by filename);
    # targets are single-slot, so always read from slot 0
    matches = [p for p in passive if get_tex_key(get_tex(p)) == active_key]

    return active, active_mtl, matches


def consolidate(context):
    """Assign the active object's source-slot material onto every other
    selected mesh that shares its source texture. Target objects are
    assumed to use a single material slot, so the material always goes
    into slot 0 there. Objects with no material slot at all are skipped.

    Returns (updated_count, skipped_count).
    """
    active, active_mtl, matches = find_matching_objects(context)

    updated = 0
    skipped = 0
    for d in matches:
        if d.material_slots:
            d.material_slots[0].material = active_mtl
            updated += 1
        else:
            skipped += 1

    return updated, skipped


def select_matching_objects(context):
    """Narrow the current selection down to the active object plus any other
    selected mesh that shares its source texture (read from the active
    object's chosen slot, and from slot 0 on every target). Returns the
    number of matching objects kept (not counting the active object
    itself)."""
    active, _active_mtl, matches = find_matching_objects(context)
    keep = set(matches)
    keep.add(active)

    for obj in context.selected_objects:
        if obj not in keep:
            obj.select_set(False)

    context.view_layer.objects.active = active
    return len(matches)


def copy_material_to_selection(context):
    """Copy the active object's source-slot material onto every other
    selected mesh, with no texture matching - this is the manual override
    for when the active object's material was just changed and the rest of
    the (already curated, e.g. via Select Matching) selection should follow
    it. Target objects are assumed to use a single material slot, so the
    material always goes into slot 0 there.

    Returns (updated_count, skipped_count).
    """
    slot_index = context.scene.port64_material_slot_index

    active = context.active_object
    if active is None:
        raise ValueError("No active object")

    active_mtl = get_mtl(active, slot_index)
    if active_mtl is None:
        raise ValueError(f"'{active.name}' has no material in slot {slot_index}")

    targets = [o for o in context.selected_objects if o != active and o.type == 'MESH']
    if not targets:
        raise ValueError("Select at least one other mesh besides the active object")

    updated = 0
    skipped = 0
    for obj in targets:
        if obj.material_slots:
            obj.material_slots[0].material = active_mtl
            updated += 1
        else:
            skipped += 1

    return updated, skipped



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

def replace_image_file(window, area, region, img, filepath):
    """Point `img` at `filepath` using the Image Editor's "Replace" operator
    rather than Image.reload(). Plain reload() has a known Blender bug
    where the image can be left magenta even though the file loads fine
    underneath - Replace does a full swap and doesn't have that issue.
    """
    area.spaces.active.image = img
    with bpy.context.temp_override(window=window, area=area, region=region):
        bpy.ops.image.replace(filepath=filepath)

def find_image_editor_area(context):
    """Return (window, area) for an Image Editor already open in the
    current window, or (None, None) if there isn't one."""
    window = context.window
    screen = window.screen if window else None
    if screen is None:
        return None, None

    for area in screen.areas:
        if area.type == 'IMAGE_EDITOR':
            return window, area
    return None, None

def find_hijack_area(context):
    """Pick an area to temporarily convert into an Image Editor, for when
    none is already open. Avoids 3D viewports so the user's viewport
    doesn't flicker/reset - only used as a last resort if it's the only
    area available."""
    window = context.window
    areas = window.screen.areas if window else []
    if not areas:
        return None, None

    non_viewport = [a for a in areas if a.type != 'VIEW_3D']
    area = non_viewport[0] if non_viewport else areas[0]
    return window, area

def run_image_replacements(window, area, region, to_process, blend_saved):
    updated = []
    for img, match in to_process:
        replace_image_file(window, area, region, img, match)
        if blend_saved:
            img.filepath = bpy.path.relpath(img.filepath)
        updated.append(img.name)
    return updated

# point every FILE-source image at its match in the texture folder using
# bpy.ops.image.replace(). That operator only runs from an Image Editor
# area: if one's already open we use it directly, otherwise we temporarily
# convert a non-viewport area into one, run every replacement through it,
# then restore that area's original type. Paths are stored relative to the
# .blend file (bpy.path.relpath) when it's been saved; otherwise there's no
# base to be relative to, so we fall back to an absolute path and let the
# caller know.
def reload_images_from_folder(context):
    folder = bpy.path.abspath(context.scene.port64_texture_folder)
    if not folder or not os.path.isdir(folder):
        raise ValueError("Texture folder is not set or doesn't exist")

    blend_saved = bool(bpy.data.filepath)

    to_process = []
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

        to_process.append((img, match))

    updated = []

    if to_process:
        window, area = find_image_editor_area(context)
        hijacked = False

        if area is None:
            window, area = find_hijack_area(context)
            if area is None:
                raise ValueError("No UI area available to run the image replace operator")
            hijacked = True

        original_type = area.type
        try:
            if hijacked:
                area.type = 'IMAGE_EDITOR'

            region = next((r for r in area.regions if r.type == 'WINDOW'), None)
            if region is None:
                raise ValueError("Image Editor area has no WINDOW region")

            updated = run_image_replacements(window, area, region, to_process, blend_saved)
        finally:
            if hijacked:
                area.type = original_type

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
            updated, skipped = consolidate(context)
        except ValueError as e:
            self.report({'WARNING'}, str(e))
            return {'CANCELLED'}

        if updated == 0 and skipped == 0:
            self.report({'INFO'}, "No matching objects found - nothing changed")
        else:
            msg = f"Updated material on {updated} object(s)"
            if skipped:
                msg += f", {skipped} skipped (no material slot)"
            self.report({'INFO'}, msg)
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


class PORT64_OT_copy_material(bpy.types.Operator):
    bl_idname = "object.port64_copy_material"
    bl_label = "Copy Material to Selection"
    bl_description = ("Copy the active object's material to every other selected mesh, "
                       "with no texture check - use to override materials on a selection "
                       "you've already curated (e.g. with Select Matching)")
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
            updated, skipped = copy_material_to_selection(context)
        except ValueError as e:
            self.report({'WARNING'}, str(e))
            return {'CANCELLED'}

        msg = f"Copied material to {updated} object(s)"
        if skipped:
            msg += f", {skipped} skipped (no material slot)"
        self.report({'INFO'}, msg)
        return {'FINISHED'}

#
# reload images
#

class PORT64_OT_reload_images(bpy.types.Operator):
    bl_idname = "image.port64_reload_images"
    bl_label = "Reload Images From Folder"
    bl_description = ("Search the texture folder for a file matching each image's current "
                       "filename (preferring a same-named .png) and replace it from there, "
                       "using Blender's Image Replace to avoid the reload magenta bug")
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

        if not_found:
            print(f"[Port64] {len(not_found)} image(s) not found in texture folder:")
            for name in sorted(not_found):
                print(f"    {name}")

        if not updated:
            msg = "No matching images found in texture folder"
            if not_found:
                msg += " - check system console"
            self.report({'WARNING'}, msg)
            return {'FINISHED'}

        msg = f"Reloaded {len(updated)} image(s)"
        if not_found:
            msg += f", {len(not_found)} not found - check system console"
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
        col.prop(context.scene, "port64_material_slot_index", text="Source Slot")
        col.operator(PORT64_OT_consolidate_materials.bl_idname, text="Consolidate Materials")

        row = col.row(align=True)
        row.operator(PORT64_OT_select_matching_textures.bl_idname, text="Select Matching")
        row.operator(PORT64_OT_copy_material.bl_idname, text="Copy Material")

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
    PORT64_OT_copy_material,
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

    bpy.types.Scene.port64_material_slot_index = bpy.props.IntProperty(
        name="Source Slot",
        description=("Material slot on the ACTIVE object used as the source when matching, "
                      "consolidating, and copying materials. Target objects are assumed to "
                      "use a single material slot (slot 0)"),
        min=0,
        default=0,
    )


def unregister():
    del bpy.types.Scene.port64_texture_folder
    del bpy.types.Scene.port64_material_slot_index

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()