import bpy
from pathlib import Path
from .merge.publish import (
    find_sync_target,
    find_all_published,
)
from .merge.shared_ids import init_shared_ids
from .merge.core import (
    ownership_get,
    ownership_set,
    get_invalid_objects,
    merge_task_layer,
)
from .merge.transfer_data.transfer_ui import draw_transfer_data
from .merge.shared_ids import get_shared_id_icon
from . import constants
from . import config
from .merge.task_layer import draw_task_layer_selection


def sync_poll(cls, context):
    if any([img.is_dirty for img in bpy.data.images]):
        cls.poll_message_set("Please save unsaved Images")
        return False
    if bpy.data.is_dirty:
        cls.poll_message_set("Please save current .blend file")
        return False
    return True


def sync_invoke(self, context):
    self._temp_transfer_data = context.scene.asset_pipeline.temp_transfer_data
    self._temp_transfer_data.clear()
    self._invalid_objs.clear()

    asset_pipe = context.scene.asset_pipeline
    local_col = asset_pipe.asset_collection
    if not local_col:
        self.report({'ERROR'}, "Top level collection could not be found")
        return {'CANCELLED'}
    # TODO Check if file contains a valid task layer
    # task_layer_key = context.scene.asset_pipeline.task_layer_name
    # if task_layer_key == "NONE":
    #     self.report({'ERROR'}, "Current File Name doesn't contain valid task layer")
    #     return {'CANCELLED'}

    ownership_get(local_col, context.scene)

    self._invalid_objs = get_invalid_objects(asset_pipe, local_col)
    self._shared_ids = init_shared_ids(context.scene)


def sync_draw(self, context):
    layout = self.layout
    row = layout.row()

    if len(self._invalid_objs) != 0:
        box = layout.box()
        box.alert = True
        box.label(text="Sync will clear Invalid Objects:", icon="ERROR")
        for obj in self._invalid_objs:
            box.label(text=obj.name, icon="OBJECT_DATA")

    if len(self._shared_ids) != 0:
        box = layout.box()
        box.label(text="New 'Shared IDs' found")
        for id in self._shared_ids:
            row = box.row()
            row.label(text=id.name, icon=get_shared_id_icon(id))
            draw_task_layer_selection(
                layout=row,
                data=id,
            )

    if len(self._temp_transfer_data) == 0:
        layout.label(text="No new local Transferable Data found")
    else:
        layout.label(text="New local Transferable Data will be Pushed to Publish")
        row = layout.row()
        row.prop(self, "expand", text="", icon="COLLAPSEMENU", toggle=False)
        row.label(text="Show New Transferable Data")
    objs = [transfer_data_item.obj for transfer_data_item in self._temp_transfer_data]

    if not self.expand:
        return

    for obj in set(objs):
        obj_ownership = [
            transfer_data_item
            for transfer_data_item in self._temp_transfer_data
            if transfer_data_item.obj == obj
        ]
        box = layout.box()
        box.label(text=obj.name, icon="OBJECT_DATA")
        draw_transfer_data(obj_ownership, box)


def sync_execute_update_ownership(self, context):
    temp_transfer_data = context.scene.asset_pipeline.temp_transfer_data
    ownership_set(temp_transfer_data)


def sync_execute_prepare_sync(self, context):
    asset_pipe = context.scene.asset_pipeline
    self._current_file = Path(bpy.data.filepath)
    self._temp_dir = Path(bpy.app.tempdir).parent
    self._task_layer_keys = asset_pipe.get_local_task_layers()
    # TODO Check if file contains a valid task layer
    # if self._task_layer_key == "NONE":
    #     self.report({'ERROR'}, "Current File Name doesn't contain valid task layer")
    #     return {'CANCELLED'}

    self._sync_target = find_sync_target(self._current_file)
    if not self._sync_target.exists():
        self.report({'ERROR'}, "Sync Target could not be determined")
        return {'CANCELLED'}

    for obj in self._invalid_objs:
        bpy.data.objects.remove(obj)


def create_temp_file_backup(self, context):
    temp_file = self._temp_dir.joinpath(
        self._current_file.name.replace(".blend", "") + "_Asset_Pipe_Backup.blend"
    )
    context.scene.asset_pipeline.temp_file = temp_file.__str__()
    return temp_file.__str__()


def update_temp_file_paths(self, context, temp_file_path):
    asset_pipe = context.scene.asset_pipeline
    asset_pipe.temp_file = temp_file_path
    asset_pipe.source_file = self._current_file.__str__()


def sync_execute_pull(self, context):
    temp_file_path = create_temp_file_backup(self, context)
    update_temp_file_paths(self, context, temp_file_path)
    bpy.ops.wm.save_as_mainfile(filepath=temp_file_path, copy=True)

    error_msg = merge_task_layer(
        context,
        local_tls=self._task_layer_keys,
        external_file=self._sync_target,
    )

    if error_msg:
        context.scene.asset_pipeline.sync_error = True
        self.report({'ERROR'}, error_msg)
        return {'CANCELLED'}


def sync_execute_push(self, context):
    temp_file_path = create_temp_file_backup(self, context)
    push_targets = find_all_published(self._current_file, constants.ACTIVE_PUBLISH_KEY)

    if self._sync_target not in push_targets:
        push_targets.append(self._sync_target)

    for file in push_targets:
        file_path = file.__str__()
        bpy.ops.wm.open_mainfile(filepath=file_path)

        update_temp_file_paths(self, context, temp_file_path)

        # SKIP DEPRECIATED FILES
        if context.scene.asset_pipeline.is_depreciated:
            continue

        local_tls = [
            task_layer
            for task_layer in config.TASK_LAYER_TYPES
            if task_layer not in self._task_layer_keys
        ]

        error_msg = merge_task_layer(
            context,
            local_tls=local_tls,
            external_file=self._current_file,
        )
        if error_msg:
            context.scene.asset_pipeline.sync_error = True
            self.report({'ERROR'}, error_msg)
            return {'CANCELLED'}

        bpy.ops.wm.save_as_mainfile(filepath=file_path)
        bpy.ops.wm.open_mainfile(filepath=self._current_file.__str__())