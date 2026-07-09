import bpy

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

# TODO: add func to override which mat is being assigned to all objs
def consolidate(context):
    """Assign the active object's material to every other selected mesh
    that shares the active object's source texture (matched by filename,
    not by Image datablock identity).

    Returns the number of objects updated. Raises ValueError with a
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

    # find objs in passive selection using the same texture (by filename) and add to list
    dupe = [p for p in passive if get_tex_key(get_tex(p)) == active_key]

    # assign active's material to all matching passive objects
    for d in dupe:
        d.data.materials.clear()
        d.data.materials.append(active_mtl)

    return len(dupe)