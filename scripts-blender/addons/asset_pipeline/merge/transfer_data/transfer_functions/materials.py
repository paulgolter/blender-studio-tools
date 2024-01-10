import bpy
from .attributes import transfer_attribute
from ..transfer_util import check_transfer_data_entry
from ...task_layer import get_transfer_data_owner
from .... import constants


def materials_clean(obj):
    # Material slots cannot use generic transfer_data_clean() function

    matches = check_transfer_data_entry(
        obj.transfer_data_ownership,
        constants.MATERIAL_TRANSFER_DATA_ITEM_NAME,
        constants.MATERIAL_SLOT_KEY,
    )

    # Clear Materials if No Transferable Data is Found
    if len(matches) != 0:
        return

    if obj.data and hasattr(obj.data, 'materials'):
        obj.data.materials.clear()


def materials_is_missing(transfer_data_item):
    if (
        transfer_data_item.type == constants.MATERIAL_SLOT_KEY
        and len(transfer_data_item.id_data.material_slots) == 0
    ):
        return True


def init_materials(scene, obj):
    asset_pipe = scene.asset_pipeline
    td_type_key = constants.MATERIAL_SLOT_KEY
    name = constants.MATERIAL_TRANSFER_DATA_ITEM_NAME
    transfer_data = obj.transfer_data_ownership

    material_objects = [
        'CURVE',
        'GPENCIL',
        'META',
        'MESH',
        'SURFACE',
        'FONT',
        'VOLUME',
    ]

    # Only Execute if Material Slots exist on object
    if obj.type not in material_objects:
        return
    matches = check_transfer_data_entry(transfer_data, name, td_type_key)
    # Only add new ownership transfer_data_item if vertex group doesn't have an owner
    if len(matches) == 0:
        task_layer_owner, auto_surrender = get_transfer_data_owner(
            asset_pipe,
            td_type_key,
        )
        asset_pipe.add_temp_transfer_data(
            name=name,
            owner=task_layer_owner,
            type=td_type_key,
            obj=obj,
            surrender=auto_surrender,
        )


def transfer_materials(target_obj: bpy.types.Object, source_obj):
    # Delete all material slots of target object.
    target_obj.data.materials.clear()

    # Transfer material slots
    for idx in range(len(source_obj.material_slots)):
        target_obj.data.materials.append(source_obj.material_slots[idx].material)
        target_obj.material_slots[idx].link = source_obj.material_slots[idx].link

    # Transfer active material slot index
    target_obj.active_material_index = source_obj.active_material_index

    # Transfer material slot assignments for curve
    if target_obj.type == "CURVE":
        for spl_to, spl_from in zip(target_obj.data.splines, source_obj.data.splines):
            spl_to.material_index = spl_from.material_index

    if source_obj.data.attributes.get(constants.MATERIAL_ATTRIBUTE_NAME):
        transfer_attribute(constants.MATERIAL_ATTRIBUTE_NAME, target_obj, source_obj)

    transfer_active_color_attribute_index(source_obj, target_obj)
    transfer_active_uv_layer_index(source_obj, target_obj)


def transfer_active_color_attribute_index(source_obj, target_obj):
    active_color_name = source_obj.data.color_attributes.active_color_name
    if active_color_name is None or active_color_name == "":
        return
    for color_attribute in target_obj.data.color_attributes:
        if color_attribute.name == active_color_name:
            target_obj.data.color_attributes.active_color = color_attribute


def transfer_active_uv_layer_index(source_obj, target_obj):
    active_uv = source_obj.data.uv_layers.active
    if active_uv is None:
        return
    for uv_layer in target_obj.data.uv_layers:
        if uv_layer.name == active_uv.name:
            target_obj.data.uv_layers.active = uv_layer
