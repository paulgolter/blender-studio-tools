from dataclasses import asdict
from typing import Any, Dict, List, Optional, Tuple

import bpy
from bpy.app.handlers import persistent

from . import opsdata, prefs
from .logger import ZLoggerFactory
from .types import ZAsset, ZAssetType, ZCache, ZProject, ZSequence, ZShot

logger = ZLoggerFactory.getLogger(name=__name__)

# CACHE VARIABLES
# used to cache active entitys to prevent a new api request when read only
_zsequence_active: ZSequence = ZSequence()
_zshot_active: ZShot = ZShot()
_zasset_active: ZAsset = ZAsset()
_zasset_type_active: ZAssetType = ZAssetType()


class BLEZOU_property_group_sequence(bpy.types.PropertyGroup):
    """
    Property group that will be registered on sequence strips.
    They hold metadata that will be used to compose a data structure that can
    be pushed to backend.
    """

    def _get_shot_description(self):
        return self.shot_description

    def _get_sequence_name(self):
        return self.sequence_name

    # shot
    shot_id: bpy.props.StringProperty(name="Shot ID")  # type: ignore
    shot_name: bpy.props.StringProperty(name="Shot", default="")  # type: ignore
    shot_description: bpy.props.StringProperty(name="Description", default="", options={"HIDDEN"})  # type: ignore

    # sequence
    sequence_name: bpy.props.StringProperty(name="Sequence", default="")  # type: ignore
    sequence_id: bpy.props.StringProperty(name="Seq ID", default="")  # type: ignore

    # project
    project_name: bpy.props.StringProperty(name="Project", default="")  # type: ignore
    project_id: bpy.props.StringProperty(name="Project ID", default="")  # type: ignore

    # meta
    initialized: bpy.props.BoolProperty(  # type: ignore
        name="Initialized", default=False, description="Is Blezou shot"
    )
    linked: bpy.props.BoolProperty(  # type: ignore
        name="Linked", default=False, description="Is linked to an ID in gazou"
    )

    # display props
    shot_description_display: bpy.props.StringProperty(name="Description", get=_get_shot_description)  # type: ignore
    sequence_name_display: bpy.props.StringProperty(name="Sequence", get=_get_sequence_name)  # type: ignore

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.shot,
            "sequence_name": self.sequence,
            "description": self.description,
        }

    def clear(self):
        self.shot_id = ""
        self.shot_name = ""
        self.shot_description = ""

        self.sequence_id = ""
        self.sequence_name = ""

        self.project_name = ""
        self.project_id = ""

        self.initialized = False
        self.linked = False

    def unlink(self):
        self.sequence_id = ""

        self.project_name = ""
        self.project_id = ""

        self.linked = False


class BLEZOU_property_group_scene(bpy.types.PropertyGroup):
    """"""

    sequence_active_id: bpy.props.StringProperty(  # type: ignore
        name="Active Sequence ID",
        description="ID that refers to the active sequence on server",
        default="",
        options={"HIDDEN", "SKIP_SAVE"},
    )
    shot_active_id: bpy.props.StringProperty(  # type: ignore
        name="Active Shot ID",
        description="IDthat refers to the active project on server",
        default="",
        options={"HIDDEN", "SKIP_SAVE"},
    )
    asset_active_id: bpy.props.StringProperty(  # type: ignore
        name="Active Asset ID",
        description="ID that refers to the active asset on server",
        default="",
        options={"HIDDEN", "SKIP_SAVE"},
    )
    asset_type_active_id: bpy.props.StringProperty(  # type: ignore
        name="Active Asset Type ID",
        description="ID that refers to the active asset type on server",
        default="",
        options={"HIDDEN", "SKIP_SAVE"},
    )

    def clear(self):
        self.sequence_active_id = ""
        self.shot_active_id = ""
        self.asset_active_id = ""
        self.asset_type_active_id = ""


class BLEZOU_property_group_window(bpy.types.PropertyGroup):
    """"""

    multi_edit_seq: bpy.props.StringProperty(  # type: ignore
        name="Sequence",
        description="",
        default="",
    )

    def clear(self):
        self.multi_edit_seq = ""


def init_cache_variables(context: bpy.types.Context = bpy.context) -> None:
    global _zsequence_active
    global _zshot_active
    global _zasset_active
    global _zasset_type_active

    sequence_active_id = context.scene.blezou.sequence_active_id
    shot_active_id = context.scene.blezou.shot_active_id
    asset_active_id = context.scene.blezou.asset_active_id
    asset_type_active_id = context.scene.blezou.asset_type_active_id

    if sequence_active_id:
        _zsequence_active = ZSequence.by_id(sequence_active_id)
        logger.info(f"Initialized active aequence cache to: {_zsequence_active.name}")

    if shot_active_id:
        _zshot_active = ZShot.by_id(shot_active_id)
        logger.info(f"Initialized active shot cache to: {_zshot_active.name}")

    if asset_active_id:
        _zasset_active = ZAsset.by_id(asset_active_id)
        logger.info(f"Initialized active asset cache to: {_zasset_active.name}")

    if asset_type_active_id:
        _zasset_type_active = ZAssetType.by_id(asset_type_active_id)
        logger.info(
            f"Initialized active asset type cache to: {_zasset_type_active.name}"
        )


def clear_cache_variables():
    global _zsequence_active
    global _zshot_active
    global _zasset_active
    global _zasset_type_active

    _zsequence_active = ZSequence()
    logger.info("Cleared active aequence cache")
    _zshot_active = ZShot()
    logger.info("Cleared active shot cache")
    _zasset_active = ZAsset()
    logger.info("Cleared active asset cache")
    _zasset_type_active = ZAssetType()
    logger.info("Cleared active asset type cache")


def _get_project_active(self):
    return prefs._zproject_active.name


def _get_sequences(self, context: bpy.types.Context) -> List[Tuple[str, str, str]]:
    addon_prefs = bpy.context.preferences.addons["blezou"].preferences
    zproject_active = prefs._zproject_active

    if not zproject_active or not addon_prefs.session.is_auth:
        return [("None", "None", "")]

    enum_list = [(s.name, s.name, "") for s in zproject_active.get_sequences_all()]
    return enum_list


def _gen_shot_preview(self):
    addon_prefs = bpy.context.preferences.addons["blezou"].preferences
    shot_counter_increment = addon_prefs.shot_counter_increment
    shot_counter_digits = addon_prefs.shot_counter_digits
    shot_counter_start = self.shot_counter_start
    shot_pattern = addon_prefs.shot_pattern
    strip = bpy.context.scene.sequence_editor.active_strip
    examples: List[str] = []
    sequence = self.sequence_enum
    var_project = (
        self.var_project_custom
        if self.var_use_custom_project
        else self.var_project_active
    )
    var_sequence = self.var_sequence_custom if self.var_use_custom_seq else sequence
    var_lookup_table = {"Sequence": var_sequence, "Project": var_project}

    for count in range(3):
        counter_number = shot_counter_start + (shot_counter_increment * count)
        counter = str(counter_number).rjust(shot_counter_digits, "0")
        var_lookup_table["Counter"] = counter
        examples.append(opsdata._resolve_pattern(shot_pattern, var_lookup_table))

    return " | ".join(examples) + "..."


def _add_window_manager_props():

    # Multi Edit Properties
    bpy.types.WindowManager.show_advanced = bpy.props.BoolProperty(
        name="Show Advanced",
        description="Shows advanced options to fine control shot pattern.",
        default=False,
    )

    bpy.types.WindowManager.var_use_custom_seq = bpy.props.BoolProperty(
        name="Use Custom",
        description="Enables to type in custom sequence name for <Sequence> wildcard.",
        default=False,
    )

    bpy.types.WindowManager.var_use_custom_project = bpy.props.BoolProperty(
        name="Use Custom",
        description="Enables to type in custom project name for <Project> wildcard",
        default=False,
    )

    bpy.types.WindowManager.var_sequence_custom = bpy.props.StringProperty(  # type: ignore
        name="Custom Sequence Variable",
        description="Value that will be used to insert in <Sequence> wildcard if custom sequence is enabled.",
        default="",
    )

    bpy.types.WindowManager.var_project_custom = bpy.props.StringProperty(  # type: ignore
        name="Custom Project Variable",
        description="Value that will be used to insert in <Project> wildcard if custom project is enabled.",
        default="",
    )

    bpy.types.WindowManager.shot_counter_start = bpy.props.IntProperty(
        description="Value that defines where the shot counter starts.",
        step=10,
        min=0,
    )

    bpy.types.WindowManager.shot_preview = bpy.props.StringProperty(
        name="Shot Pattern",
        description="Preview result of current settings on how a shot will be named.",
        get=_gen_shot_preview,
    )

    bpy.types.WindowManager.var_project_active = bpy.props.StringProperty(
        name="Active Project",
        description="Value that will be inserted in <Project> wildcard.",
        get=_get_project_active,
    )

    bpy.types.WindowManager.sequence_enum = bpy.props.EnumProperty(
        name="Sequences",
        items=_get_sequences,
        description="Name of Sequence the generated Shots will be assinged to.",
    )

    # advanced delete props
    bpy.types.WindowManager.advanced_delete = bpy.props.BoolProperty(
        name="Advanced Delete",
        description="Checkbox to show advanced shot deletion operations.",
        default=False,
    )


def _clear_window_manager_props():
    del bpy.types.WindowManager.show_advanced
    del bpy.types.WindowManager.var_use_custom_seq
    del bpy.types.WindowManager.var_use_custom_project
    del bpy.types.WindowManager.var_sequence_custom
    del bpy.types.WindowManager.var_project_custom
    del bpy.types.WindowManager.shot_counter_start
    del bpy.types.WindowManager.shot_preview
    del bpy.types.WindowManager.var_project_active
    del bpy.types.WindowManager.sequence_enum


@persistent
def load_post_handler(dummy):
    clear_cache_variables()


# ----------------REGISTER--------------

classes = [BLEZOU_property_group_sequence, BLEZOU_property_group_scene]


def register():

    for cls in classes:
        bpy.utils.register_class(cls)

    # Sequence Properties
    bpy.types.Sequence.blezou = bpy.props.PointerProperty(
        name="Blezou",
        type=BLEZOU_property_group_sequence,
        description="Metadata that is required for blezou",
    )
    # Scene Properties
    bpy.types.Scene.blezou = bpy.props.PointerProperty(
        name="Blezou",
        type=BLEZOU_property_group_scene,
        description="Metadata that is required for blezou",
    )
    # Window Manager Properties
    _add_window_manager_props()

    # Handlers
    bpy.app.handlers.load_post.append(load_post_handler)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

    # clear cache
    clear_cache_variables()

    # clear properties
    _clear_window_manager_props()

    # clear handlers
    bpy.app.handlers.load_post.remove(load_post_handler)
