import bpy
from typing import List
from bpy.types import PropertyGroup, Object, Operator, Action, ShapeKey
from bpy.props import (
	PointerProperty, IntProperty, CollectionProperty, StringProperty, 
	BoolProperty
)
from mathutils import Vector
from math import sqrt
from .symmetrize_shape_key import mirror_mesh

# When saving or pushing shapes, disable any modifier NOT in this list.
DEFORM_MODIFIERS = ['ARMATURE', 'CAST', 'CURVE', 'DISPLACE', 'HOOK', 
'LAPLACIANDEFORM', 'LATTICE', 'MESH_DEFORM', 'SHRINKWRAP', 'SIMPLE_DEFORM', 
'SMOOTH', 'CORRECTIVE_SMOOTH', 'LAPLACIANSMOOTH', 'SURFACE_DEFORM', 'WARP', 
'WAVE']

def get_addon_prefs(context):
	return context.preferences.addons[__package__].preferences

class PoseShapeKeyTarget(PropertyGroup):
	def update_name(self, context):
		if self.block_name_update:
			return
		ob = context.object
		if not ob.data.shape_keys:
			return
		sk = ob.data.shape_keys.key_blocks.get(self.shape_key_name)
		if sk:
			sk.name = self.name
		self.shape_key_name = self.name

	def update_shape_key_name(self, context):
		self.block_name_update = True
		self.name = self.shape_key_name
		self.block_name_update = False

	name: StringProperty(
		name = "Shape Key Target"
		,description = "Name of this shape key target. Should stay in sync with the displayed name and the shape key name, unless the shape key is renamed outside of our UI"
		,update = update_name
	)
	mirror_x: BoolProperty(
		name = "Mirror X"
		,description = "Mirror the shape key on the X axis when applying the shape to this shape key"
		,default = False
	)

	block_name_update: BoolProperty(
		description = "Flag to help keep shape key names in sync"
		,default = False
	)
	shape_key_name: StringProperty(
		name = "Shape Key"
		,description = "Name of the shape key to push data to"
		,update = update_shape_key_name
	)


	@property
	def key_block(self) -> List[ShapeKey]:
		mesh = self.id_data
		if not mesh.shape_keys:
			return
		return mesh.shape_keys.key_blocks.get(self.name)

class PoseShapeKey(PropertyGroup):
	target_shapes: CollectionProperty(type=PoseShapeKeyTarget)

	def update_active_sk_index(self, context):
		ob = context.object
		if not ob.data.shape_keys:
			return
		try:
			sk_name = self.target_shapes[self.active_target_shape_index].shape_key_name
		except IndexError:
			ob.active_shape_key_index = len(ob.data.shape_keys.key_blocks)-1
			return
		key_block_idx = ob.data.shape_keys.key_blocks.find(sk_name)
		if key_block_idx > -1:
			ob.active_shape_key_index = key_block_idx

	active_target_shape_index: IntProperty(update=update_active_sk_index)

	action: PointerProperty(
		name="Action"
		,type=Action
		,description = "Action that contains the frame that should be used when applying the stored shape as a shape key"
	)
	frame: IntProperty(
		name = "Frame"
		,description = "Frame that should be used within the selected action when applying the stored shape as a shape key"
		,default = 0
	)
	storage_object: PointerProperty(
		type = Object
		,name = "Storage Object"
		,description = "Specify an object that stores the vertex position data"
	)

def get_deforming_armature(mesh_ob: Object) -> Object:
	for m in mesh_ob.modifiers:
		if m.type=='ARMATURE':
			return m.object

class OBJECT_OT_Create_ShapeKey_For_Pose(Operator):
	"""Create and assign a Shape Key"""

	bl_idname = "object.create_shape_key_for_pose"
	bl_label = "Create Shape Key"
	bl_options = {'UNDO', 'REGISTER', 'INTERNAL'}
	bl_property = "sk_name"


	def update_sk_name(self, context):

		def set_vg(vg_name):
			ob = context.object
			vg = ob.vertex_groups.get(vg_name)
			if vg:
				self.vg_name = vg.name
				return vg

		ob = context.object
		vg = set_vg(self.sk_name)
		if not vg and self.sk_name.endswith(".L"):
			vg = set_vg("Side.L")
		if not vg and self.sk_name.endswith(".R"):
			vg = set_vg("Side.R")

	sk_name: StringProperty(
		name = "Name"
		,description = "Name to set for the new shape key"
		,default = "Key"
		,update = update_sk_name
	)
	vg_name: StringProperty(
		name = "Vertex Group"
		,description = "Vertex Group to assign as the masking group of this shape key"
		,default = ""
	)

	def invoke(self, context, event):
		ob = context.object
		if ob.data.shape_keys:
			self.sk_name = f"Key {len(ob.data.shape_keys.key_blocks)}"
		else:
			self.sk_name = "Key"
		
		pose_key = ob.data.pose_keys[ob.data.active_pose_key_index]
		if pose_key.name:
			self.sk_name = pose_key.name

		return context.window_manager.invoke_props_dialog(self)

	def draw(self, context):
		layout = self.layout
		layout.prop(self, 'sk_name')
		ob = context.object
		layout.prop_search(self, 'vg_name', ob, "vertex_groups")

	def execute(self, context):
		ob = context.object

		# Ensure Basis shape key
		if not ob.data.shape_keys:
			basis = ob.shape_key_add()
			basis.name = "Basis"
			ob.data.update()

		# Add new shape key
		new_sk = ob.shape_key_add()
		new_sk.name = self.sk_name
		new_sk.value = 1
		if self.vg_name:
			new_sk.vertex_group = self.vg_name

		pose_key = ob.data.pose_keys[ob.data.active_pose_key_index]
		target = pose_key.target_shapes[pose_key.active_target_shape_index]
		target.name = new_sk.name

		self.report({'INFO'}, f"Added shape key {new_sk.name}.")
		return {'FINISHED'}

class SaveAndRestoreState:
	def disable_non_deform_modifiers(self, storage_ob: Object, rigged_ob: Object):
		# Disable non-deforming modifiers
		self.disabled_mods_storage = []
		self.disabled_mods_rigged = []
		for ob, lst in zip([storage_ob, rigged_ob], [self.disabled_mods_storage, self.disabled_mods_rigged]):
			if not ob: continue
			for m in ob.modifiers:
				if m.type not in DEFORM_MODIFIERS and m.show_viewport:
					lst.append(m.name)
					m.show_viewport = False

	def restore_non_deform_modifiers(self, storage_ob: Object, rigged_ob: Object):
		# Re-enable non-deforming modifiers
		for ob, m_list in zip([storage_ob, rigged_ob], [self.disabled_mods_storage, self.disabled_mods_rigged]):
			if not ob: continue
			for m_name in m_list:
				ob.modifiers[m_name].show_viewport = True

	def save_state(self, context):
		rigged_ob = context.object

		pose_key = rigged_ob.data.pose_keys[rigged_ob.data.active_pose_key_index]
		storage_ob = pose_key.storage_object

		# Non-Deforming modifiers
		self.disable_non_deform_modifiers(storage_ob, rigged_ob)

		# Active Shape Key Index
		self.orig_sk_index = rigged_ob.active_shape_key_index
		rigged_ob.active_shape_key_index = 0

		# Shape Keys
		self.org_sk_toggles = {}
		for target_shape in pose_key.target_shapes:
			key_block = target_shape.key_block
			if not key_block:
				self.report({'ERROR'}, f"Shape key not found: {key_block.name}")
				return {'CANCELLED'}
			self.org_sk_toggles[key_block.name] = key_block.mute
			key_block.mute = True

	def restore_state(self, context):
		rigged_ob = context.object
		pose_key = rigged_ob.data.pose_keys[rigged_ob.data.active_pose_key_index]
		storage_ob = pose_key.storage_object
		self.restore_non_deform_modifiers(storage_ob, rigged_ob)

		rigged_ob.active_shape_key_index = self.orig_sk_index
		for kb_name, kb_value in self.org_sk_toggles.items():
			rigged_ob.data.shape_keys.key_blocks[kb_name].mute = kb_value

class OperatorWithWarning:
	def invoke(self, context, event):
		addon_prefs = get_addon_prefs(context)
		if addon_prefs.no_warning:
			return self.execute(context)

		return context.window_manager.invoke_props_dialog(self, width=400)

	def draw(self, context):
		layout = self.layout.column(align=True)

		warning = self.get_warning_text(context)
		for line in warning.split("\n"):
			row = layout.row()
			row.alert = True
			row.label(text=line)

		addon_prefs = get_addon_prefs(context)
		col = layout.column(align=True)
		col.prop(addon_prefs, 'no_warning', text="Disable Warnings (Can be reset in Preferences)")

	def get_warning_text(self, context):
		raise NotImplemented

class OBJECT_OT_PoseKey_Set_Pose(Operator):
	"""Set the rig pose to the specified action and frame (Reset any other posing)"""

	bl_idname = "object.posekey_set_pose"
	bl_label = "Set Pose"
	bl_options = {'UNDO', 'REGISTER', 'INTERNAL'}

	@classmethod
	def poll(cls, context):
		rigged_ob = context.object
		arm_ob = get_deforming_armature(rigged_ob)
		if not arm_ob:
			return False
		if rigged_ob.type != 'MESH' or not rigged_ob.data.shape_keys:
			return False
		if len(rigged_ob.data.pose_keys) == 0:
			return True
		pose_key = rigged_ob.data.pose_keys[rigged_ob.data.active_pose_key_index]
		if not pose_key.action:
			return False

		return True

	def execute(self, context):
		bpy.ops.object.posekey_reset_rig()

		rigged_ob = context.object
		pose_key = rigged_ob.data.pose_keys[rigged_ob.data.active_pose_key_index]

		arm_ob = get_deforming_armature(rigged_ob)
		if pose_key.action:
			# Set Action and Frame to get the right pose
			arm_ob.animation_data.action = pose_key.action
			context.scene.frame_current = pose_key.frame

		return {'FINISHED'}

def get_active_pose_key(ob):
	if len(ob.data.pose_keys) == 0:
		return

	return ob.data.pose_keys[ob.data.active_pose_key_index]

def verify_pose(context):
	"""To make these operators foolproof, there are a lot of checks to make sure
	that the user gets to see the effect of the operator. The "Set Pose" operator
	can be used first to set the correct state and pass all the checks here.
	"""
	ob = context.object

	pose_key = get_active_pose_key(ob)
	if not pose_key:
		return False

	# No shape keys to push into
	any_target_keys = False
	for target_shape in pose_key.target_shapes:
		if target_shape.key_block != None:
			any_target_keys = True
			break
	if not any_target_keys:
		return False

	# An action is specified but not active on the armature
	arm_ob = get_deforming_armature(ob)
	if not arm_ob:
		return True
	if pose_key.action and not arm_ob.animation_data:
		return False
	if arm_ob.animation_data.action != pose_key.action:
		return False
	
	# An action is specified but frame number mismatches
	if pose_key.action and pose_key.frame != context.scene.frame_current:
		return False

	return True

class OBJECT_OT_PoseKey_Save(Operator, OperatorWithWarning, SaveAndRestoreState):
	"""Save the current evaluated mesh vertex positions into the Storage Object"""

	bl_idname = "object.posekey_save"
	bl_label = "Overwrite Storage Object"
	bl_options = {'UNDO', 'REGISTER', 'INTERNAL'}

	@classmethod
	def poll(cls, context):

		ob = context.object
		# No storage object to read from
		pose_key = get_active_pose_key(ob)
		if pose_key and not pose_key.storage_object:
			return True
		return verify_pose(context)

	def invoke(self, context, event):
		ob = context.object
		pose_key = ob.data.pose_keys[ob.data.active_pose_key_index]
		if pose_key.storage_object:
			return super().invoke(context, event)
		return self.execute(context)

	def get_warning_text(self, context):
		ob = context.object
		pose_key = ob.data.pose_keys[ob.data.active_pose_key_index]
		return f'This will overwrite "{pose_key.storage_object.name}".\n Are you sure?'

	def execute(self, context):
		rigged_ob = context.object

		pose_key = rigged_ob.data.pose_keys[rigged_ob.data.active_pose_key_index]
		storage_ob = pose_key.storage_object
		self.disable_non_deform_modifiers(storage_ob, rigged_ob)

		depsgraph = context.evaluated_depsgraph_get()
		rigged_ob_eval = rigged_ob.evaluated_get(depsgraph)
		rigged_ob_eval_mesh = rigged_ob_eval.data

		storage_ob_name = rigged_ob.name + "." + pose_key.name
		storage_ob_mesh = bpy.data.meshes.new_from_object(rigged_ob)
		storage_ob_mesh.name = storage_ob_name

		if not storage_ob:
			storage_ob = bpy.data.objects.new(storage_ob_name, storage_ob_mesh)
			context.scene.collection.objects.link(storage_ob)
			pose_key.storage_object = storage_ob
			storage_ob.location = rigged_ob.location
			storage_ob.location.x -= rigged_ob.dimensions.x * 1.1

			# Set action and frame number to the current ones, in case the user
			# is already in the desired pose for this pose key.
			arm_ob = get_deforming_armature(rigged_ob)
			if arm_ob and arm_ob.animation_data and arm_ob.animation_data.action:
				pose_key.action = arm_ob.animation_data.action
				pose_key.frame = context.scene.frame_current
		else:
			old_mesh = storage_ob.data
			storage_ob.data = storage_ob_mesh
			bpy.data.meshes.remove(old_mesh)

		if len(storage_ob.data.vertices) != len(rigged_ob.data.vertices):
			self.report({'WARNING'}, f'Vertex Count did not match between storage object {storage_ob.name}({len(storage_ob.data.vertices)}) and current ({len(rigged_ob.data.vertices)})!')
			storage_ob_mesh = bpy.data.meshes.new_from_object(rigged_ob_eval)
			storage_ob.data = storage_ob_mesh
			storage_ob.data.name = storage_ob_name

		storage_ob.use_shape_key_edit_mode = True
		storage_ob.shape_key_add(name="Basis")
		target = storage_ob.shape_key_add(name="Morph Target")
		adjust = storage_ob.shape_key_add(name="New Changes", from_mix=True)
		target.value = 1
		adjust.value = 1
		storage_ob.active_shape_key_index = 2

		# Set the target shape to be the evaluated mesh.
		for target_v, eval_v in zip(target.data, rigged_ob_eval_mesh.vertices):
			target_v.co = eval_v.co

		# Copy some symmetry settings from the original
		storage_ob.data.use_mirror_x = rigged_ob.data.use_mirror_x

		# Nuke vertex groups, since we don't need them.
		storage_ob.vertex_groups.clear()

		self.restore_non_deform_modifiers(storage_ob, rigged_ob)

		# If new shape is visible, set it as active.
		if storage_ob.visible_get():
			bpy.ops.object.mode_set(mode='OBJECT')
			bpy.ops.object.select_all(action='DESELECT')
			context.view_layer.objects.active = storage_ob
			storage_ob.select_set(True)

		self.report({'INFO'}, f'The deformed mesh has been stored in "{storage_ob.name}".')
		return {'FINISHED'}

class OBJECT_OT_PoseKey_Push(Operator, OperatorWithWarning, SaveAndRestoreState):
	"""Let the below shape keys blend the current deformed shape into the shape of the Storage Object"""

	bl_idname = "object.posekey_push"
	bl_label = "Load Vertex Position Data into Shape Keys"
	bl_options = {'UNDO', 'REGISTER', 'INTERNAL'}

	@classmethod
	def poll(cls, context):
		return verify_pose(context)

	def get_warning_text(self, context):
		ob = context.object
		pose_key = ob.data.pose_keys[ob.data.active_pose_key_index]
		target_shape_names = [target.name for target in pose_key.target_shapes if target]
		return "This will overwrite the following Shape Keys: \n    " + "\n    ".join(target_shape_names) +"\n Are you sure?"

	def execute(self, context):
		"""
		Load the active PoseShapeKey's mesh data into its corresponding shape key,
		such that the shape key will blend from whatever state the mesh is currently in,
		into the shape stored in the PoseShapeKey.
		"""

		rigged_ob = context.object
		pose_key = rigged_ob.data.pose_keys[rigged_ob.data.active_pose_key_index]

		storage_object = pose_key.storage_object
		if storage_object.name not in context.view_layer.objects:
			self.report({'ERROR'}, "Storage object must be in view layer.")
			return {'CANCELLED'}

		self.save_state(context)

		depsgraph = context.evaluated_depsgraph_get()
		scene = context.scene

		# The Pose Key stores the vertex positions of a previous evaluated mesh.
		# This, and the current vertex positions of the mesh are subtracted
		# from each other to get the difference in their shape.
		storage_eval_verts = pose_key.storage_object.evaluated_get(depsgraph).data.vertices
		rigged_eval_verts = rigged_ob.evaluated_get(depsgraph).data.vertices

		# Shape keys are relative to the base shape of the mesh, so that delta
		# will be added to the base mesh to get the final shape key vertex positions.
		rigged_base_verts = rigged_ob.data.vertices

		# The CrazySpace provides us the matrix by which each vertex has been 
		# deformed by modifiers and shape keys. This matrix is necessary to 
		# calculate the correct delta.
		rigged_ob.crazyspace_eval(depsgraph, scene)

		for i, v in enumerate(storage_eval_verts):
			if i > len(rigged_base_verts)-1:
				break
			storage_eval_co = Vector(v.co)
			rigged_eval_co = rigged_eval_verts[i].co

			delta = storage_eval_co - rigged_eval_co

			delta = rigged_ob.crazyspace_displacement_to_original(vertex_index=i, displacement=delta)

			base_v = rigged_base_verts[i].co
			for target_shape in pose_key.target_shapes:
				key_block = target_shape.key_block
				if not key_block: continue
				key_block.data[i].co = base_v+delta

		# Mirror shapes if needed
		for target_shape in pose_key.target_shapes:
			if target_shape.mirror_x:
				key_block = target_shape.key_block
				if not key_block: continue
				mirror_mesh(
					reference_verts = rigged_ob.data.vertices
					,vertices = key_block.data
					,axis = 'X'
					,symmetrize = False
				)

		rigged_ob.crazyspace_eval_clear()

		self.restore_state(context)

		if len(storage_eval_verts) != len(rigged_eval_verts):
			self.report({'WARNING'}, f"Mismatching topology: Stored shape had {len(storage_eval_verts)} vertices instead of {len(rigged_eval_verts)}")

		return {'FINISHED'}

class OBJECT_OT_PoseKey_Normalize(Operator, OperatorWithWarning):
	"""Normalize the mask vertex groups of the shape keys"""

	bl_idname = "object.posekey_normalize"
	bl_label = "Normalize Vertex Group Masks"
	bl_options = {'UNDO', 'REGISTER', 'INTERNAL'}

	@staticmethod
	def get_affected_vertex_group_names(context) -> List[str]:
		ob = context.object
		pose_key = ob.data.pose_keys[ob.data.active_pose_key_index]

		vg_names = []
		for target_shape in pose_key.target_shapes:
			kb = target_shape.key_block
			if not kb: continue
			if kb.vertex_group and kb.vertex_group in ob.vertex_groups:
				vg_names.append(kb.vertex_group)
		
		return vg_names

	@classmethod
	def poll(cls, context):
		return cls.get_affected_vertex_group_names(context)

	def get_warning_text(self, context):
		ob = context.object
		vg_names = self.get_affected_vertex_group_names(context)
		return "The weights of these vertex groups will add up to 1.0 for each vertex:\n    " + "\n    ".join(vg_names) +"\n Are you sure?"

	@staticmethod
	def normalize_vgroups(o, vgroups):
		""" Normalize a set of vertex groups in isolation """
		""" Used for creating mask vertex groups for splitting shape keys """
		for v in o.data.vertices:
			# Find sum of weights in specified vgroups
			# set weight to original/sum
			sum_weights = 0
			for vg in vgroups:
				w = 0
				try:
					sum_weights += vg.weight(v.index)
				except:
					pass
			for vg in vgroups:
				try:
					vg.add([v.index], vg.weight(v.index)/sum_weights, 'REPLACE')
				except:
					pass

	def execute(self, context):
		vg_names = self.get_affected_vertex_group_names(context)
		ob = context.object
		self.normalize_vgroups(ob, [ob.vertex_groups[vg_name] for vg_name in vg_names])
		return {'FINISHED'}

class OBJECT_OT_PoseKey_Place_Objects_In_Grid(Operator):
	"""Place the storage objects in a grid above this object"""

	bl_idname = "object.posekey_object_grid"
	bl_label = "Place Objects In Grid"
	bl_options = {'UNDO', 'REGISTER', 'INTERNAL'}

	@staticmethod
	def get_storage_objects(context) -> List[Object]:
		ob = context.object
		pose_keys = ob.data.pose_keys
		return [pk.storage_object for pk in pose_keys if pk.storage_object]

	@classmethod
	def poll(cls, context):
		"""Only available if there are any storage objects in any of the pose keys."""
		return cls.get_storage_objects(context)

	@staticmethod
	def place_objects_in_grid(context, objs: List[Object]):
		dimensions = context.object.dimensions.copy() * Vector((1.2, 1.2, 1.2))

		grid_rows = round(sqrt(len(objs)))
		for i, ob in enumerate(objs):
			col_i = (i % grid_rows) - int(grid_rows / 2)
			row_i = int(i / grid_rows) + 1.2
			offset = Vector((col_i * dimensions.x, 0, row_i * dimensions.z))
			ob.location = context.object.location + offset

	def execute(self, context):
		storage_objects = self.get_storage_objects(context)
		self.place_objects_in_grid(context, storage_objects)

		return {'FINISHED'}

class OBJECT_OT_PoseKey_Jump_To_Shape(Operator):
	"""Place the storage object next to this object and select it"""

	bl_idname = "object.posekey_jump_to_storage"
	bl_label = "Jump To Storage Object"
	bl_options = {'UNDO', 'REGISTER', 'INTERNAL'}

	@staticmethod
	def get_storage_object(context):
		ob = context.object
		pose_key = ob.data.pose_keys[ob.data.active_pose_key_index]
		return pose_key.storage_object

	@classmethod
	def poll(cls, context):
		"""Only available if there is a storage object in the pose key."""
		return cls.get_storage_object(context)

	def execute(self, context):
		storage_object = self.get_storage_object(context)

		storage_object.location = context.object.location
		storage_object.location.x -= context.object.dimensions.x * 1.1

		if storage_object.name not in context.view_layer.objects:
			self.report({'ERROR'}, "Storage object must be in view layer.")
			return {'CANCELLED'}
		bpy.ops.object.select_all(action='DESELECT')
		storage_object.select_set(True)
		storage_object.hide_set(False)
		context.view_layer.objects.active = storage_object

		# Put the other storage objects in a grid
		prefs = get_addon_prefs(context)
		if prefs.grid_objects_on_jump:
			storage_objects = OBJECT_OT_PoseKey_Place_Objects_In_Grid.get_storage_objects(context)
			storage_objects.remove(storage_object)
			OBJECT_OT_PoseKey_Place_Objects_In_Grid.place_objects_in_grid(context, storage_objects)

		return {'FINISHED'}

registry = [
	PoseShapeKeyTarget
	,PoseShapeKey
	,OBJECT_OT_PoseKey_Save
	,OBJECT_OT_PoseKey_Set_Pose
	,OBJECT_OT_PoseKey_Push
	,OBJECT_OT_Create_ShapeKey_For_Pose
	,OBJECT_OT_PoseKey_Normalize
	,OBJECT_OT_PoseKey_Place_Objects_In_Grid
	,OBJECT_OT_PoseKey_Jump_To_Shape
]

def update_posekey_index(self, context):
	# Want to piggyback on update_active_sk_index() to also update the active
	# shape key index when switching pose keys.
	mesh = context.object.data
	if mesh.pose_keys:
		pk = mesh.pose_keys[mesh.active_pose_key_index]
		# We just want to fire the update func.
		pk.active_target_shape_index = pk.active_target_shape_index

def register():
	bpy.types.Mesh.pose_keys = CollectionProperty(type=PoseShapeKey)
	bpy.types.Mesh.active_pose_key_index = IntProperty(update=update_posekey_index)

def unregister():
	del bpy.types.Mesh.pose_keys
	del bpy.types.Mesh.active_pose_key_index
