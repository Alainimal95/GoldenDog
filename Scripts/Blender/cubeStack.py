# unwraps and stacks faces on a cube
#must be in edit mode, only one obj selected
#assumes relevant selection has been made
import bpy

act = bpy.context.active_object
mesh = bpy.ops.mesh

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
proj_size = 1.05 * max(act.dimensions)
bpy.ops.uv.cube_project(cube_size=proj_size)