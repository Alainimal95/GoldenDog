bl_info = {
    "name": "Stack",
    "author": "Hypernova",
    "version": (0, 0, 2),
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
from mathutils import Vector

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

# stack islands
def stack_islands():
    # move the 2d cursor to the middle of the UV editor
    bpy.ops.uv.cursor_set(location=(0.5, 0.5))
    
    # ensure selection is linked between viewport and UV editor -- if that matters
    
    # create a stack(set) from the face list
    
    # while there are items in this set:
        # select a face in the stack and it's UV island neighbors, then remove them from the stack
        # capture here
        
        # move the island to the 2d cursor
        
        
        # clear the selection

# cube stack
def cube_stack():    
    seam_grid()
    # cube_tile_project()
    # stack_islands()


# ---------------------------------------------------------------------------
# operators
# ---------------------------------------------------------------------------

# cube stack
class STACK_OT_cube_stack(bpy.types.Operator):
    bl_label = "Cube Stack"
    bl_idname = "stack.cube_stack"
    bl_options = {'REGISTER', 'UNDO'}
    
    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and obj.type == 'MESH' and obj.mode == 'EDIT'

    def execute(self, context):
        #obj = context.object
        try:
            cube_stack()
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
bpy.ops.stack.cube_stack()