# unwraps and stacks faces on a cube
#must be in edit mode, only one obj selected
#assumes relevant selection has been made
import bpy

act = bpy.context.active_object
mesh = bpy.ops.mesh

#
# helper funcs
#

# select by normal
def select_by_normal(sel, axis)
    # clear selection
    mesh.select_all(action='DESELECT')
    # pick axis
    axis = []
        
    # select faces with normals aligned to this axis 
    sel = 
    
    return sel 

#
# add seams
#
"""

#under construction -- for more advanced stacking

# switch to edge select mode
bpy.ops.object.mode_set(mode='EDIT')
mesh.select_mode(type='EDGE')

# add seams to sharp edges (approx 85 deg)
mesh.select_all(action='DESELECT')
mesh.edges_select_sharp(sharpness=1.5)
mesh.mark_seam(clear=False)
"""
#
# stack
#

# cube project
mesh.select_all(action='SELECT')

#get object dimensions and shortest axis
size = act.dimensions
size_min = min(dim)

# tiling on shortest axis
tile = 1
tile_scale =tile*size_min 

#select by normal (list per axis)
polys = act.data.polygons


proj_size = 1.05 * tile_scale
bpy.ops.uv.cube_project(cube_size=proj_size)