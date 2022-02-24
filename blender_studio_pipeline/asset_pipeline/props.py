# ***** BEGIN GPL LICENSE BLOCK *****
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software Foundation,
# Inc., 59 Temple Place - Suite 330, Boston, MA  02111-1307, USA.
#
# ***** END GPL LICENCE BLOCK *****
#
# (c) 2021, Blender Foundation - Paul Golter
from typing import Optional, Dict, Any

from pathlib import Path

import bpy

from . import constants
from . import builder
from .builder.metadata import MetadataAsset, MetadataTaskLayer
from .asset_files import AssetPublish


class BSP_ASSET_asset_collection(bpy.types.PropertyGroup):
    """
    Collection Properties for Blender Studio Asset Collections
    """

    is_asset: bpy.props.BoolProperty(  # type: ignore
        name="Is Asset",
        default=False,
        description="Controls if this Collection is recognized as an official Asset",
    )

    # We use entity_ prefix as blender uses .id as built in attribute already, which
    # might be confusing.
    entity_name: bpy.props.StringProperty(name="Asset Name")  # type: ignore
    entity_id: bpy.props.StringProperty(name="Asset ID")  # type: ignore

    version: bpy.props.StringProperty(name="Asset Version")  # type: ignore
    status: bpy.props.StringProperty(name="Asset Status", default=constants.DEFAULT_ASSET_STATUS)  # type: ignore
    project_id: bpy.props.StringProperty(name="Project ID")  # type: ignore

    rig: bpy.props.PointerProperty(type=bpy.types.Armature, name="Rig")  # type: ignore

    transfer_suffix: bpy.props.StringProperty(name="Transfer Suffix")  # type: ignore

    # Display properties that can't be set by User in UI.
    displ_entity_name: bpy.props.StringProperty(name="Asset Name", get=lambda self: self.entity_name)  # type: ignore
    displ_entity_id: bpy.props.StringProperty(name="Asset ID", get=lambda self: self.entity_id)  # type: ignore

    def clear(self) -> None:
        self.is_asset = False
        self.entity_name = ""
        self.entity_id = ""
        self.version = ""
        self.project_id = ""
        self.rig = None

    def gen_metadata_class(self) -> MetadataAsset:
        # These keys represent all mandatory arguments for the data class metadata.MetaAsset
        # The idea is, to be able to construct a MetaAsst from this dict.
        keys = ["entity_name", "entity_id", "project_id", "version", "status"]
        d = {}
        for key in keys:

            # MetaAsset tries to mirror Kitsu data structure as much as possible.
            # Remove entity_ prefix.
            if key.startswith("entity_"):
                d[key.replace("entity_", "")] = getattr(self, key)
            else:
                d[key] = getattr(self, key)

        return MetadataAsset.from_dict(d)


class BSP_task_layer(bpy.types.PropertyGroup):

    """
    Property Group that can represent a minimal TaskLayer.
    Note: It misses properties compared to MetadataTaskLayer class, contains only the ones
    needed for internal use. Also contains 'use' attribute to avoid creating a new property group
    to mimic more the TaskLayer TaskLayerConfig setup.
    Is used in BSP_ASSET_scene_properties as collection property.
    """

    task_layer_id: bpy.props.StringProperty(  # type: ignore
        name="Task Layer ID",
        description="Unique Key that is used to query a Task Layer in TaskLayerAssembly.get_task_layer_config()",
    )
    task_layer_name: bpy.props.StringProperty(  # type: ignore
        name="Task Layer Name",
    )

    is_locked: bpy.props.BoolProperty(  # type: ignore
        name="Is Locked",
    )

    use: bpy.props.BoolProperty(  # type: ignore
        name="Use",
    )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "use": self.use,
            "is_locked": self.is_locked,
            "task_layer_id": self.task_layer_id,
            "task_layer_name": self.task_layer_name,
        }


class BSP_asset_file(bpy.types.PropertyGroup):

    """
    Property Group that can represent a minimal version of an Asset File.
    """

    path_str: bpy.props.StringProperty(  # type: ignore
        name="Path",
    )
    task_layers: bpy.props.CollectionProperty(type=BSP_task_layer)  # type: ignore

    status: bpy.props.StringProperty(name="Status")  # type: ignore

    @property
    def path(self) -> Optional[Path]:
        if not self.path_str:
            return None
        return Path(self.path_str)

    def as_dict(self) -> Dict[str, Any]:
        return {"path": self.path}

    def add_task_layer_from_metaclass(self, metadata_task_layer: MetadataTaskLayer):
        item = self.task_layers.add()
        # TODO: could be made more procedural.
        item.task_layer_id = metadata_task_layer.id
        item.task_layer_name = metadata_task_layer.name
        item.is_locked = metadata_task_layer.is_locked


class BSP_undo_context(bpy.types.PropertyGroup):

    """ """

    files_created: bpy.props.CollectionProperty(type=BSP_asset_file)  # type: ignore

    def add_step_asset_publish_create(self, asset_publish: AssetPublish) -> None:
        item = self.files_created.add()
        item.path_str = asset_publish.path.as_posix()

    def clear(self):
        self.files_created.clear()


class BSP_task_layer_lock_plan(bpy.types.PropertyGroup):

    """
    Property Group that can represent a minimal version of a TaskLayerLockPlan.
    """

    path_str: bpy.props.StringProperty(  # type: ignore
        name="Path",
    )
    task_layers: bpy.props.CollectionProperty(type=BSP_task_layer)  # type: ignore

    @property
    def path(self) -> Optional[Path]:
        if not self.path_str:
            return None
        return Path(self.path_str)


class BSP_ASSET_scene_properties(bpy.types.PropertyGroup):
    """
    Scene Properties for Asset Pipeline
    """

    # Gets set by BSP_ASSET_init_asset_collection
    asset_collection: bpy.props.PointerProperty(type=bpy.types.Collection)  # type: ignore

    # Display properties that can't be set by User in UI.
    displ_asset_collection: bpy.props.StringProperty(name="Asset Collection", get=lambda self: self.asset_collection.name)  # type: ignore

    # There should only be one asset_collection per working task.
    # We don't want that the User can directly set the tasks Asset Collection.
    # The tmp_asset_collection property is used for the
    # BSP_ASSET_init_asset_collection operator to know what Collection it should initialize as Asset Collection.
    # This logic prevents having multiple Asset Collection per scene and forces user to clear the Asset Collection
    # before initializing another one.
    tmp_asset_collection: bpy.props.PointerProperty(type=bpy.types.Collection)  # type: ignore

    is_publish_in_progress: bpy.props.BoolProperty()  # type: ignore
    are_task_layers_pushed: bpy.props.BoolProperty()  # type: ignore

    task_layers: bpy.props.CollectionProperty(type=BSP_task_layer)  # type: ignore

    asset_publishes: bpy.props.CollectionProperty(type=BSP_asset_file)  # type: ignore

    task_layers_index: bpy.props.IntProperty(name="Task Layers Index", min=0)  # type: ignore
    asset_publishes_index: bpy.props.IntProperty(name="Asset Publishes Index", min=0)  # type: ignore
    task_layer_lock_plans_index: bpy.props.IntProperty(name="Task Layer Lock Plans Index", min=0)  # type: ignore

    undo_context: bpy.props.PointerProperty(type=BSP_undo_context)  # type: ignore

    task_layer_lock_plans: bpy.props.CollectionProperty(type=BSP_task_layer_lock_plan)  # type: ignore


def get_asset_publish_source_path(context: bpy.types.Context) -> str:
    if not builder.ASSET_CONTEXT:
        return ""

    if not builder.ASSET_CONTEXT.asset_publishes:
        return ""

    return builder.ASSET_CONTEXT.asset_publishes[-1].path.name


class BSP_ASSET_tmp_properties(bpy.types.PropertyGroup):

    # Asset publish source
    asset_publish_source_path: bpy.props.StringProperty(  # type: ignore
        name="Source", get=get_asset_publish_source_path
    )

    new_asset_version: bpy.props.BoolProperty(  # type: ignore
        name="New Version",
        description="Controls if new Version should be created when starting the publish",
    )


# ----------------REGISTER--------------.

classes = [
    BSP_task_layer,
    BSP_asset_file,
    BSP_undo_context,
    BSP_ASSET_asset_collection,
    BSP_task_layer_lock_plan,
    BSP_ASSET_scene_properties,
    BSP_ASSET_tmp_properties,
]


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)

    # Collection Asset Pipeline Properties.
    bpy.types.Collection.bsp_asset = bpy.props.PointerProperty(
        type=BSP_ASSET_asset_collection
    )

    # Scene Asset Pipeline Properties.
    bpy.types.Scene.bsp_asset = bpy.props.PointerProperty(
        type=BSP_ASSET_scene_properties
    )

    # Window Manager Properties.
    bpy.types.WindowManager.bsp_asset = bpy.props.PointerProperty(
        type=BSP_ASSET_tmp_properties
    )


def unregister() -> None:
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
