bl_info = {
    "name": "Stack",
    "author": "Hypernova",
    "version": (0, 0, 3),
    "blender": (5, 0, 1),
    "location": "View3D > Edit Mesh > Select",
    "description": "Stack similar mesh islands on top of each other",
    "category": "UV",
}
# unwraps and stacks faces on a cube / object with modular square faces/regions
# must be in edit mode, only one obj selected
# assumes relevant selection has been made
import bpy
import bmesh
import random

act = bpy.context.active_object
mesh = bpy.ops.mesh

# ---------------------------------------------------------------------------
# helper funcs
# ---------------------------------------------------------------------------

# get min edge length of bmesh edge list
def get_shortest_edges(edges):
    # get edge lengths
    edge_lengths = [e.calc_length() for e in edges]
    min_length = min(edge_lengths)
    shortest_edges = [e for e in edges if e.calc_length() == min_length]
    for e in edges:
        if e not in shortest_edges:
            e.select = False
    

# put seams at the boundaries of square regions
def seam_grid():
    bm = bmesh.from_edit_mesh(act.data)
    
    # select shortest edges in selection
    edges = bm.edges
    sel_edges = [e for e in edges if e.select == True]
    shortest_edges = get_shortest_edges(sel_edges)
    bm.select_flush_mode()
    bmesh.update_edit_mesh(act.data)
        
    # add seams
    bpy.ops.mesh.mark_seam(clear=False)
    
    # clear selection
    bpy.ops.mesh.select_all(action='DESELECT')

# cube tile project
def cube_tile_project():
    # TEMP: capture selection
    mesh.select_all(action='SELECT')

    # TEMP: get bbox dimensions and shortest axis of selection
    size = act.dimensions
    size_min = min(size)

    # tiling on shortest axis
    tile = 1
    tile_scale =tile*size_min 

    # box project UVs
    proj_size = tile_scale
    bpy.ops.uv.cube_project(cube_size=proj_size)
    
    # restore original selection
    bpy.ops.mesh.select_all(action='DESELECT')

def find_UV_editor_area():
    """Return (window, area) for an UV editor already open in the
    current window, or (None, None) if there isn't one."""
    window = bpy.context.window
    screen = window.screen if window else None
    if screen is None:
        return None, None
 
    for area in screen.areas:
        if area.type == 'IMAGE_EDITOR' and area.ui_type == 'UV':
            return window, area
    return None, None

def find_hijack_area():
    """Pick an area to temporarily convert into an UV editor, for when
    none is already open. Avoids 3D viewports so the user's viewport
    doesn't flicker/reset - only used as a last resort if it's the only
    area available."""
    window = bpy.context.window
    areas = window.screen.areas if window else []
    if not areas:
        return None, None
 
    non_viewport = [a for a in areas if a.type != 'VIEW_3D']
    area = non_viewport[0] if non_viewport else areas[0]
    return window, area
 
# find the WINDOW region of a given area
def find_uv_region(area):
    return next((r for r in area.regions if r.type == 'WINDOW'), None)

# set 2d cursor location
def set_2d_cursor(x, y, window, area):
    with bpy.context.temp_override(window=window, area=area):
        bpy.ops.uv.cursor_set(location=(x, y))
        
# unwrap 
def unwrap(window, area):
    with bpy.context.temp_override(window=window, area=area):
        bpy.ops.uv.unwrap(method='ANGLE_BASED')
        
# snap island to cursor
def snap_island_to_cursor(window, area):
    with bpy.context.temp_override(window=window, area=area):
        bpy.ops.uv.snap_selected(target='CURSOR_OFFSET')

# stack islands
def stack_islands(window, area, verify=False):
    print("Stacking")
    # UV sync selection must be on, otherwise uv.snap_selected acts on the
    # UV editor's own (stale) selection buffer instead of mirroring whatever
    # mesh faces we select via select_linked below
    ts = bpy.context.scene.tool_settings
    prev_sync = ts.use_uv_select_sync
    ts.use_uv_select_sync = True
    
    # select all faces, create bmesh and face stack from the selected
    bpy.ops.object.mode_set(mode='EDIT') 
    bpy.ops.mesh.select_all(action='SELECT')
    bm = bmesh.from_edit_mesh(act.data)
    bm.faces.ensure_lookup_table
    sel_faces = [f.index for f in bm.faces if f.select == True]
    face_stack = list(sel_faces)
    
    # debug
    print("Face stack: ")
    print(face_stack)
    
    # move the 2d cursor to the middle of the UV editor
    set_2d_cursor(0.5, 0.5, window, area)
    
    # deselect all mesh elements
    bpy.ops.mesh.select_all(action='DESELECT')
    bpy.ops.mesh.select_mode(use_extend=False, use_expand=False, type='FACE')
    
    # grid layout spacing for verify mode - wide enough that projected
    # islands (roughly 0-1 in UV space each) can't touch neighboring cells
    verify_cols = 5
    verify_spacing = 1.5
    
    i = 0

    while face_stack:  
        # refresh bmesh
        bm = bmesh.from_edit_mesh(act.data)
        bm.faces.ensure_lookup_table()
        
        # select a face in the stack and its UV island neighbors
        
        seed = bm.faces[face_stack[0]]
        print("Seed index: " + str(seed.index))
        seed.select = True
        bmesh.update_edit_mesh(act.data)
        
        bpy.ops.mesh.select_linked(delimit={'SEAM'})
        
        # unwrap the island
        unwrap(window, area)
        
        # re-fetch bm after the op - selection state is only valid now
        bm = bmesh.from_edit_mesh(act.data)
        bm.faces.ensure_lookup_table()
        island = [f.index for f in bm.faces if f.select]
        
        # debug
        print("Island: " + str(i))
        for idx in island:
            print(idx)
        
        # verify mode: give each island its own grid cell so shapes can
        # be inspected with zero ambiguity - no overlap, no sticky
        # selection interference, since nothing is actually coincident.
        # normal mode: every island goes to the same point, on purpose.
        if verify:
            col = i % verify_cols
            row = i // verify_cols
            cursor_x = 0.5 + col * verify_spacing
            cursor_y = 0.5 + row * verify_spacing
        else:
            cursor_x, cursor_y = 0.5, 0.5
        set_2d_cursor(cursor_x, cursor_y, window, area)
            
        # move the island to the 2d cursor
        snap_island_to_cursor(window, area)
        
        # remove island members from the remaining stack
        face_stack = [idx for idx in face_stack if idx not in island]
 
        # deselect the island for the next pass
        bm = bmesh.from_edit_mesh(act.data)
        bm.faces.ensure_lookup_table()
        for idx in island:
            bm.faces[idx].select = False
        bmesh.update_edit_mesh(act.data)
 
        # debug
        if not island: print("Island cleared")
            
        i += 1
        

def hijack_and_stack(verify=False):
    # find open image edtor if available
    window, area = find_UV_editor_area()
    hijacked = False
    
    # if no UV editor, pick one that isn't a viewport and hijack it temporarily
    if area is None:
        window, area = find_hijack_area()
        if area is None:
            raise ValueError("No UI area available to run the image replace operator")
        hijacked = True

    # capture original area type
    original_type = area.type
    
    try:
        # switch to image edtor
        if hijacked:
            area.type = 'IMAGE_EDITOR'
            area.ui_type = 'UV'
        """
        region = next((r for r in area.regions if r.type == 'WINDOW'), None)
        if region is None:
            raise ValueError("UV editor area has no WINDOW region")
        """

        stack_islands(window, area, verify=verify)
    
    # restore original area type
    finally:
        if hijacked:
            area.type = original_type
    
    

# cube stack
def cube_stack(verify=False):    
    seam_grid()
    cube_tile_project()
    hijack_and_stack(verify=verify)
    
    print("Finished")


# ---------------------------------------------------------------------------
# operators
# ---------------------------------------------------------------------------

# cube stack
class STACK_OT_cube_stack(bpy.types.Operator):
    bl_label = "Cube Stack"
    bl_idname = "stack.cube_stack"
    bl_options = {'REGISTER', 'UNDO'}
    
    verify: bpy.props.BoolProperty(
        name="Verify Layout",
        description="Spread islands across a grid instead of stacking them on top of each other, so each can be visually inspected for correct separation before doing the real stack",
        default=True,
    )
    
    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and obj.type == 'MESH' and obj.mode == 'EDIT'

    def execute(self, context):
        #obj = context.object
        try:
            cube_stack(verify=self.verify)
        except RuntimeError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        return {'FINISHED'}
    
# ---------------------------------------------------------------------------
# panel
# ---------------------------------------------------------------------------

# class STACK_PT_cube_stack(bpy.types.Panel)

# ---------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------

classes = (
    STACK_OT_cube_stack,
    )

scene = bpy.types.Scene

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
    
#test call
callID = random.randint(1, 1000)
print("\n" + "Start of call: " + str(callID) + "\n")
bpy.ops.stack.cube_stack()
print("\n" + "End of call: " + str(callID) + "\n")