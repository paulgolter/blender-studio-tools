import bpy
from mathutils import Matrix, Vector
from bpy.types import Gizmo, Object
import numpy as np
import gpu

from .shapes import Circle2D, Cross2D, MeshShape3D

class MoveBoneGizmo(Gizmo):
	"""In order to avoid re-implementing logic for transforming bones with 
	mouse movements, this gizmo instead binds its offset value to the
	bpy.ops.transform.translate operator, giving us all that behaviour for free.
	(Important behaviours like auto-keying, precision, snapping, axis locking, etc)
	The downside of this is that we can't customize that behaviour very well,
	for example we can't get the gizmo to draw during mouse interaction,
	we can't hide the mouse cursor, etc. Minor sacrifices.
	"""

	bl_idname = "GIZMO_GT_bone_gizmo"
	# The id must be "offset"
	bl_target_properties = (
		{"id": "offset", "type": 'FLOAT', "array_length": 3},
	)

	__slots__ = (
		# This __slots__ thing allows us to use arbitrary Python variable 
		# assignments on instances of this gizmo.
		"bone_name"			# Name of the bone that owns this gizmo.
		,"props"			# Instance of BoneGizmoProperties that's stored on the bone that owns this gizmo.

		,"custom_shape"
		,"meshshape"

		,"color_backup"
		,"alpha_backup"

		,"gizmo_group"
	)

	def setup(self):
		"""Called by Blender when the Gizmo is created."""
		self.meshshape = None
		self.custom_shape = None

	def init_shape(self, context):
		"""Should be called by the GizmoGroup, after it assigns the neccessary 
		custom properties to properly initialize this Gizmo."""
		props = self.props

		if not self.poll(context):
			return

		if self.is_using_vgroup():
			self.load_shape_vertex_group(props.shape_object, props.vertex_group_name)
		elif self.is_using_facemap():
			# We use the built-in function to draw face maps, so we don't need to do any extra processing.
			pass
		else:
			self.load_shape_entire_object()

	def init_properties(self):
		props = self.props
		self.line_width = self.line_width
		self.init_colors()

	def init_colors(self):
		props = self.props
		if self.is_using_bone_group_colors():
			pb = self.get_pose_bone()
			self.color = pb.bone_group.colors.normal[:]
			self.color_highlight = pb.bone_group.colors.select[:]
			self.alpha = 0.2
			self.alpha_highlight = 0.4
		else:
			self.color = props.color[:3]
			self.alpha = props.color[3]

			self.color_highlight = props.color_highlight[:3]
			self.alpha_highlight = props.color_highlight[3]

	def poll(self, context):
		"""Whether any gizmo logic should be executed or not. This function is not
		from the API! Call this manually to prevent logic execution.
		"""
		pb = self.get_pose_bone(context)
		bone_visible = pb and not pb.bone.hide and any(bl and al for bl, al in zip(pb.bone.layers[:], pb.id_data.data.layers[:]))

		return self.props.shape_object and self.props.enabled and bone_visible

	def load_shape_vertex_group(self, obj, v_grp: str, weight_threshold=0.2, widget_scale=1.05):
		"""Update the vertex indicies that the gizmo shape corresponds to when using
		vertex group masking.
		This is very expensive, should only be called on initial Gizmo creation, 
		manual updates, and changing of	gizmo display object or mask group.
		"""
		self.meshshape = MeshShape3D(obj, scale=widget_scale, vertex_groups=[v_grp], weight_threshold=weight_threshold)

	def refresh_shape_vgroup(self, context, eval_mesh):
		"""Update the custom shape based on the stored vertex indices."""
		if not self.meshshape:
			self.init_shape(context)
		if len(self.meshshape._indices) < 3:
			return
		self.custom_shape = self.new_custom_shape('TRIS', self.meshshape.get_vertices(eval_mesh))
		return True

	def load_shape_entire_object(self):
		"""Update the custom shape to an entire object. This is somewhat expensive,
		should only be called when Gizmo display object is changed or mask
		facemap/vgroup is cleared.
		"""
		mesh = self.props.shape_object.data
		vertices = np.zeros((len(mesh.vertices), 3), 'f')
		mesh.vertices.foreach_get("co", vertices.ravel())

		if self.props.draw_style == 'POINTS':
			custom_shape_verts = vertices

		elif self.props.draw_style == 'LINES':
			edges = np.zeros((len(mesh.edges), 2), 'i')
			mesh.edges.foreach_get("vertices", edges.ravel())
			custom_shape_verts = vertices[edges].reshape(-1,3)

		elif self.props.draw_style == 'TRIS':
			mesh.calc_loop_triangles()
			tris = np.zeros((len(mesh.loop_triangles), 3), 'i')
			mesh.loop_triangles.foreach_get("vertices", tris.ravel())
			custom_shape_verts = vertices[tris].reshape(-1,3)

		self.custom_shape = self.new_custom_shape(self.props.draw_style, custom_shape_verts)

	def draw_shape(self, context, select_id=None):
		"""Shared drawing logic for selection and color.
		The actual color seems to be determined deeper, between self.color and self.color_highlight.
		"""

		face_map = self.props.shape_object.face_maps.get(self.props.face_map_name)
		if face_map and self.props.use_face_map:
			self.draw_preset_facemap(self.props.shape_object, face_map.index, select_id=select_id or 0)
		elif self.custom_shape:
			self.draw_custom_shape(self.custom_shape, select_id=select_id)
		else:
			# This can happen if the specified vertex group is empty.
			return

	def draw_shared(self, context, select_id=None):
		if not self.poll(context):
			return
		if not self.props.shape_object:
			return
		self.update_basis_and_offset_matrix(context)

		gpu.state.line_width_set(self.line_width)
		gpu.state.blend_set('MULTIPLY')
		self.draw_shape(context, select_id)
		gpu.state.blend_set('NONE')
		gpu.state.line_width_set(1)

	def draw(self, context):
		"""Called by Blender on every viewport update (including mouse moves).
		Drawing functions called at this time will draw into the color pass.
		"""
		if not self.poll(context):
			return
		if self.use_draw_hover and not self.is_highlight:
			return

		pb = self.get_pose_bone(context)
		if pb.bone.select and not self.select:
			# If the bone just got selected, swap the colors.
			self.color_backup = self.color.copy()
			self.alpha_backup = self.alpha
			self.color = self.color_highlight
			self.alpha = self.alpha_highlight
		elif self.select and not pb.bone.select and hasattr(self, 'color_backup'):
			# If the bone just got unselected, swap the colors back.
			self.color = self.color_backup.copy()
			self.alpha = self.alpha_backup

		self.select = pb.bone.select
		self.draw_shared(context)

	def draw_select(self, context, select_id):
		"""Called by Blender on every viewport update (including mouse moves).
		Drawing functions called at this time will draw into an invisible pass
		that is used for mouse interaction.
		"""
		if not self.poll(context):
			return
		self.draw_shared(context, select_id)

	def is_using_vgroup(self):
		props = self.props
		return not props.use_face_map and props.shape_object and props.vertex_group_name in props.shape_object.vertex_groups

	def is_using_facemap(self):
		props = self.props
		return props.use_face_map and props.face_map_name in props.shape_object.face_maps

	def is_using_bone_group_colors(self):
		pb = self.get_pose_bone()
		props = self.props
		return pb and pb.bone_group and pb.bone_group.color_set != 'DEFAULT' and props.use_bone_group_color

	def get_pose_bone(self, context=None):
		if not context:
			context = bpy.context
		arm_ob = context.object
		return arm_ob.pose.bones.get(self.bone_name)

	def get_bone_matrix(self, context):
		pb = self.get_pose_bone(context)
		return pb.matrix.copy()

	def update_basis_and_offset_matrix(self, context):
		pb = self.get_pose_bone(context)
		self.matrix_basis = self.props.shape_object.matrix_world

		if not self.is_using_facemap() and not self.is_using_vgroup():
			rest_matrix = pb.bone.matrix_local.copy()
			pose_matrix = pb.matrix.copy()

			delta_mat = pose_matrix @ rest_matrix.inverted()

			self.matrix_offset = delta_mat
		else:
			self.matrix_offset = Matrix.Identity(4)

	def invoke(self, context, event):
		armature = context.object
		if not event.shift:
			for pb in armature.pose.bones:
				pb.bone.select = False
		pb = self.get_pose_bone(context)
		pb.bone.select = True
		armature.data.bones.active = pb.bone
		return {'RUNNING_MODAL'}

	def exit(self, context, cancel):
		return

	def modal(self, context, event, tweak):
		return {'RUNNING_MODAL'}

classes = (
	MoveBoneGizmo,
)

register, unregister = bpy.utils.register_classes_factory(classes)
