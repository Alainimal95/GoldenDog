import bpy

# get slot 0 material
"""
TODO: may have to add search functionality here if
used on objs with multiple mat slots
"""
def get_mtl(obj):
	mtl = obj.material_slots[0].material
	return(mtl)

# check texture
def get_tex(obj):

	# get obj's node tree (first material slot)
	nodes = get_mtl(obj).node_tree.nodes

	# get texture node from tree
	tex = [n for n in nodes if n.type == 'TEX_IMAGE']
	tex = tex[0].image
	return(tex)

# 
# consolidate materials
# 
def consolidate():
    # capture active and passive selected objects
    sel = bpy.context.selected_objects
    active = bpy.context.active_object
    # passive
    passive = [s for s in sel if s != active]

    # get active object's material
    active_mtl = get_mtl(active)

    # get active object's texture
    active_tex = get_tex(active)

    # find objs in passive selection using same texture and add to list
    dupe = [p for p in passive if active_tex == get_tex(p)]

    # assign active's material to all matching passive objects
    for d in dupe:
	   d.data.materials.clear()
	   d.data.materials.append(active_mtl)
    
    
consolidate()