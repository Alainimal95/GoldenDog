#Rescale
#uniformly scales selected objects (from world origin) with one click and applies the scale

import bpy

#capture scale amount (default 100)
s = 100
scale = (s, s, s)

#set pivot - may add more options later if needed
pivot = (0, 0, 0)

#scale and apply
bpy.ops.transform.resize(value=(scale), center_override=(pivot))
bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)