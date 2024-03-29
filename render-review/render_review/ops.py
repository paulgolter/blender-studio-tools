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

import sys
import subprocess
import shutil
from pathlib import Path
from typing import Set, Union, Optional, List, Dict, Any, Tuple

import bpy

from render_review import vars, prefs, opsdata, util, kitsu

from render_review.exception import NoImageSequenceAvailableException
from render_review.log import LoggerFactory

logger = LoggerFactory.getLogger(name=__name__)


class RR_OT_sqe_create_review_session(bpy.types.Operator):
    """
    Has to modes to either review sequence or a single shot.
    Review shot will load all available preview sequences (.jpg / .png) of each found rendering
    in to the sequence editor of the specified shot.
    Review sequence does it for each shot in that sequence.
    If user enabled use_blender_kitsu in the addon preferences,
    this operator will create a linked metastrip for the loaded shot on the top most channel.
    """

    bl_idname = "rr.sqe_create_review_session"
    bl_label = "Create Review Session"
    bl_description = (
        "Imports all available renderings for the specified shot / sequence "
        "in to the sequence editor"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        render_dir = context.scene.rr.render_dir_path
        if not render_dir:
            return False
        return bool(
            context.scene.rr.is_render_dir_valid
            and opsdata.is_shot_dir(render_dir)
            or opsdata.is_sequence_dir(render_dir)
        )

    def execute(self, context: bpy.types.Context) -> Set[str]:
        addon_prefs = prefs.addon_prefs_get(context)
        render_dir = Path(context.scene.rr.render_dir_path)
        shot_folders: List[Path] = []

        # If render is sequence folder user wants to review whole sequence.
        if opsdata.is_sequence_dir(render_dir):
            shot_folders.extend(list(render_dir.iterdir()))
        else:
            shot_folders.append(render_dir)

        shot_folders.sort(key=lambda d: d.name)
        prev_frame_end: int = 0

        for shot_folder in shot_folders:

            logger.info("Processing %s", shot_folder.name)

            imported_sequences: bpy.types.ImageSequence = []

            # Find existing output dirs.
            shot_name = opsdata.get_shot_name_from_dir(shot_folder)
            output_dirs = [
                d
                for d in shot_folder.iterdir()
                if d.is_dir() and "__intermediate" not in d.name
            ]
            output_dirs = sorted(output_dirs, key=lambda d: d.name)

            # 070_0010_A.lighting is the latest render > with current structure
            # This folder is [0] in output dirs > needs to be moved to [-1].
            output_dirs.append(output_dirs[0])
            output_dirs.pop(0)

            # Init sqe.
            if not context.scene.sequence_editor:
                context.scene.sequence_editor_create()

            # Load preview sequences in vse.
            for idx, dir in enumerate(output_dirs):
                # Compose frames found text.
                frames_found_text = opsdata.gen_frames_found_text(dir)

                try:
                    # Get best preview files sequence.
                    image_sequence = opsdata.get_best_preview_sequence(dir)

                except NoImageSequenceAvailableException:
                    # if no preview files available create an empty image strip
                    # this assumes that when a folder is there exr sequences are available to inspect
                    logger.warning("%s found no preview sequence", dir.name)
                    exr_files = opsdata.gather_files_by_suffix(
                        dir, output=list, search_suffixes=[".exr"]
                    )

                    if not exr_files:
                        logger.error("%s found no exr or preview sequence", dir.name)
                        continue

                    image_sequence = exr_files[0]
                    logger.info("%s found %i exr frames", dir.name, len(image_sequence))

                else:
                    logger.info(
                        "%s found %i preview frames", dir.name, len(image_sequence)
                    )

                finally:

                    # Get frame start.
                    frame_start = prev_frame_end or int(image_sequence[0].stem)

                    # Create new image strip.
                    strip = context.scene.sequence_editor.sequences.new_image(
                        dir.name,
                        image_sequence[0].as_posix(),
                        idx + 1,
                        frame_start,
                    )

                    # Extend strip elements with all the available frames.
                    for f in image_sequence[1:]:
                        strip.elements.append(f.name)

                    # Set strip properties.
                    strip.mute = True if image_sequence[0].suffix == ".exr" else False
                    strip.rr.shot_name = shot_folder.name
                    strip.rr.is_render = True
                    strip.rr.frames_found_text = frames_found_text

                    imported_sequences.append(strip)

            # Query the strip that is the longest for metastrip and prev_frame_end.
            imported_sequences.sort(key=lambda s: s.frame_final_duration)
            strip_longest = imported_sequences[-1]

            # Perform kitsu operations if enabled.
            if (
                addon_prefs.enable_blender_kitsu
                and prefs.is_blender_kitsu_enabled()
                and imported_sequences
            ):

                if kitsu.is_auth_and_project():

                    shot_name = shot_folder.name
                    sequence_name = shot_folder.parent.name

                    # Create metastrip.
                    metastrip = kitsu.create_meta_strip(context, strip_longest)

                    # Link metastrip.
                    kitsu.link_strip_by_name(
                        context, metastrip, shot_name, sequence_name
                    )

                else:
                    logger.error(
                        "Unable to perform kitsu operations. No active project or no authorized"
                    )

            prev_frame_end = strip_longest.frame_final_end

        # Set scene resolution to resolution of loaded image.
        context.scene.render.resolution_x = vars.RESOLUTION[0]
        context.scene.render.resolution_y = vars.RESOLUTION[1]

        # Change frame range and frame start.
        opsdata.fit_frame_range_to_strips(context)
        context.scene.frame_current = context.scene.frame_start

        # Setup color management.
        opsdata.setup_color_management(bpy.context)

        # scan for approved renders, will modify strip.rr.is_approved prop
        # which controls the custom gpu overlay
        opsdata.update_is_approved(context)
        util.redraw_ui()

        self.report(
            {"INFO"},
            f"Imported {len(imported_sequences)} Render Sequences",
        )

        return {"FINISHED"}


class RR_OT_setup_review_workspace(bpy.types.Operator):
    """
    Makes Video Editing Workspace active and deletes all other workspaces.
    Replaces File Browser area with Image Editor.
    """

    bl_idname = "rr.setup_review_workspace"
    bl_label = "Setup Review Workspace"
    bl_description = (
        "Makes Video Editing Workspace active and deletes all other workspaces."
        "Replaces File Browser area with Image Editor"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: bpy.types.Context) -> Set[str]:

        # Remove non video editing workspaces.
        for ws in bpy.data.workspaces:
            if ws.name != "Video Editing":
                bpy.ops.workspace.delete({"workspace": ws})

        # Add / load video editing workspace.
        if "Video Editing" not in [ws.name for ws in bpy.data.workspaces]:
            blender_version = bpy.app.version  # gets (3, 0, 0)
            blender_version_str = f"{blender_version[0]}.{blender_version[1]}"
            ws_filepath = (
                Path(bpy.path.abspath(bpy.app.binary_path)).parent
                / blender_version_str
                / "scripts/startup/bl_app_templates_system/Video_Editing/startup.blend"
            )
            bpy.ops.workspace.append_activate(
                idname="Video Editing",
                filepath=ws_filepath.as_posix(),
            )
        else:
            context.window.workspace = bpy.data.workspaces["Video Editing"]

        # Change video editing workspace media browser to image editor.
        for window in context.window_manager.windows:
            screen = window.screen

            for area in screen.areas:
                if area.type == "FILE_BROWSER":
                    area.type = "IMAGE_EDITOR"

        # Init sqe.
        if not context.scene.sequence_editor:
            context.scene.sequence_editor_create()

        # Setup color management.
        opsdata.setup_color_management(bpy.context)

        self.report({"INFO"}, "Setup Render Review Workspace")

        return {"FINISHED"}


class RR_OT_sqe_inspect_exr_sequence(bpy.types.Operator):
    bl_idname = "rr.sqe_inspect_exr_sequence"
    bl_label = "Inspect EXR"
    bl_description = (
        "If available loads EXR sequence for selected sequence strip in image editor"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        active_strip = context.scene.sequence_editor.active_strip
        image_editor = opsdata.get_image_editor(context)
        return bool(
            active_strip
            and active_strip.type == "IMAGE"
            and active_strip.rr.is_render
            and image_editor
        )

    def execute(self, context: bpy.types.Context) -> Set[str]:
        active_strip = context.scene.sequence_editor.active_strip
        image_editor = opsdata.get_image_editor(context)
        output_dir = Path(bpy.path.abspath(active_strip.directory))

        # Find exr sequence.
        exr_seq = [
            f for f in output_dir.iterdir() if f.is_file() and f.suffix == ".exr"
        ]
        if not exr_seq:
            self.report({"ERROR"}, f"Found no exr sequence in: {output_dir.as_posix()}")
            return {"CANCELLED"}

        exr_seq.sort(key=lambda p: p.name)
        exr_seq_frame_start = int(exr_seq[0].stem)
        offset = exr_seq_frame_start - active_strip.frame_final_start

        # Remove all images with same filepath that are already loaded.
        img_to_rm: bpy.types.Image = []
        for img in bpy.data.images:
            if Path(bpy.path.abspath(img.filepath)) == exr_seq[0]:
                img_to_rm.append(img)

        for img in img_to_rm:
            bpy.data.images.remove(img)

        # Create new image datablock.
        image = bpy.data.images.load(exr_seq[0].as_posix(), check_existing=True)
        image.name = exr_seq[0].parent.name + "_RENDER"
        image.source = "SEQUENCE"
        image.colorspace_settings.name = "Linear"

        # Set active image.
        image_editor.spaces.active.image = image
        image_editor.spaces.active.image_user.frame_duration = 5000
        image_editor.spaces.active.image_user.frame_offset = offset

        return {"FINISHED"}


class RR_OT_sqe_clear_exr_inspect(bpy.types.Operator):
    bl_idname = "rr.sqe_clear_exr_inspect"
    bl_label = "Clear EXR Inspect"
    bl_description = "Removes the active image from the image editor"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        image_editor = cls._get_image_editor(context)
        return bool(image_editor and image_editor.spaces.active.image)

    def execute(self, context: bpy.types.Context) -> Set[str]:
        image_editor = self._get_image_editor(context)
        image_editor.spaces.active.image = None
        return {"FINISHED"}

    @classmethod
    def _get_image_editor(self, context: bpy.types.Context) -> Optional[bpy.types.Area]:

        image_editor = None

        for area in bpy.context.screen.areas:
            if area.type == "IMAGE_EDITOR":
                image_editor = area

        return image_editor


class RR_OT_sqe_approve_render(bpy.types.Operator):
    bl_idname = "rr.sqe_approve_render"
    bl_label = "Approve Render"
    bl_description = (
        "Copies the selected strip render from the farm_output to the shot_frames directory."
        "Existing render in shot_frames will be renamed for extra backup"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        active_strip = context.scene.sequence_editor.active_strip
        addon_prefs = prefs.addon_prefs_get(bpy.context)

        return bool(
            addon_prefs.is_shot_frames_valid
            and active_strip
            and active_strip.type == "IMAGE"
            and active_strip.rr.is_render
        )

    def execute(self, context: bpy.types.Context) -> Set[str]:

        active_strip = context.scene.sequence_editor.active_strip
        strip_dir = Path(bpy.path.abspath(active_strip.directory))
        shot_frames_dir = opsdata.get_shot_frames_dir(active_strip)
        shot_frames_backup_path = opsdata.get_shot_frames_backup_path(active_strip)
        metadata_path = opsdata.get_shot_frames_metadata_path(active_strip)

        # Create Shot Frames path if not exists yet.
        if shot_frames_dir.exists():

            # Delete backup if exists.
            if shot_frames_backup_path.exists():
                shutil.rmtree(shot_frames_backup_path)

            # Rename current to backup.
            shot_frames_dir.rename(shot_frames_backup_path)
            logger.info(
                "Created backup: %s > %s",
                shot_frames_dir.name,
                shot_frames_backup_path.name,
            )
        else:
            shot_frames_dir.mkdir(parents=True)
            logger.info("Created dir in Shot Frames: %s", shot_frames_dir.as_posix())

        # Copy dir.
        opsdata.copytree_verbose(
            strip_dir,
            shot_frames_dir,
            dirs_exist_ok=True,
        )
        logger.info(
            "Copied: %s \nTo: %s", strip_dir.as_posix(), shot_frames_dir.as_posix()
        )

        # Update metadata json.
        if not metadata_path.exists():
            metadata_path.touch()
            opsdata.save_to_json(
                {"source_current": strip_dir.as_posix(), "source_backup": ""},
                metadata_path,
            )
            logger.info("Created metadata.json: %s", metadata_path.as_posix())
        else:
            json_dict = opsdata.load_json(metadata_path)
            # Source backup will get value from old source current.
            json_dict["source_backup"] = json_dict["source_current"]
            # Source current will get value from strip dir.
            json_dict["source_current"] = strip_dir.as_posix()

            opsdata.save_to_json(json_dict, metadata_path)

        # Scan for approved renders.
        opsdata.update_is_approved(context)
        util.redraw_ui()

        # Log.
        self.report({"INFO"}, f"Updated {shot_frames_dir.name} in Shot Frames")
        logger.info("Updated metadata in: %s", metadata_path.as_posix())

        return {"FINISHED"}

    def invoke(self, context, event):
        active_strip = context.scene.sequence_editor.active_strip
        shot_frames_dir = opsdata.get_shot_frames_dir(active_strip)
        width = 200 + len(shot_frames_dir.as_posix()) * 5
        return context.window_manager.invoke_props_dialog(self, width=width)

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        active_strip = context.scene.sequence_editor.active_strip
        strip_dir = Path(bpy.path.abspath(active_strip.directory))
        shot_frames_dir = opsdata.get_shot_frames_dir(active_strip)

        layout.separator()
        layout.row(align=True).label(text="From Farm Output:", icon="RENDER_ANIMATION")
        layout.row(align=True).label(text=strip_dir.as_posix())

        layout.separator()
        layout.row(align=True).label(text="To Shot Frames:", icon="FILE_TICK")
        layout.row(align=True).label(text=shot_frames_dir.as_posix())

        layout.separator()
        layout.row(align=True).label(text="Update Shot Frames?")


class RR_OT_sqe_update_is_approved(bpy.types.Operator):
    bl_idname = "rr.update_is_approved"
    bl_label = "Update is Approved"
    bl_description = (
        "Scans sequence editor and checks for each render strip if it is approved."
        "by reading the metadata.json file"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        return bool(context.scene.sequence_editor.sequences_all)

    def execute(self, context: bpy.types.Context) -> Set[str]:
        approved_strips = opsdata.update_is_approved(context)

        if approved_strips:
            self.report(
                {"INFO"},
                f"Found approved {'render' if len(approved_strips) == 1 else 'renders'}: {', '.join(s.name for s in approved_strips)}",
            )
        else:
            self.report({"INFO"}, "Found no approved renders")
        return {"FINISHED"}


class RR_OT_open_path(bpy.types.Operator):
    """
    Opens cls.filepath in explorer. Supported for win / mac / linux.
    """

    bl_idname = "rr.open_path"
    bl_label = "Open Path"
    bl_description = "Opens filepath in system default file browser"

    filepath: bpy.props.StringProperty(  # type: ignore
        name="Filepath",
        description="Filepath that will be opened in explorer",
        default="",
    )

    def execute(self, context: bpy.types.Context) -> Set[str]:

        if not self.filepath:
            self.report({"ERROR"}, "Can't open empty path in explorer")
            return {"CANCELLED"}

        filepath = Path(self.filepath)
        if filepath.is_file():
            filepath = filepath.parent

        if not filepath.exists():
            filepath = self._find_latest_existing_folder(filepath)

        if sys.platform == "darwin":
            subprocess.check_call(["open", filepath.as_posix()])

        elif sys.platform == "linux2" or sys.platform == "linux":
            subprocess.check_call(["xdg-open", filepath.as_posix()])

        elif sys.platform == "win32":
            os.startfile(filepath.as_posix())

        else:
            self.report(
                {"ERROR"}, f"Can't open explorer. Unsupported platform {sys.platform}"
            )
            return {"CANCELLED"}

        return {"FINISHED"}

    def _find_latest_existing_folder(self, path: Path) -> Path:
        if path.exists() and path.is_dir():
            return path
        else:
            return self._find_latest_existing_folder(path.parent)


class RR_OT_sqe_isolate_strip_exit(bpy.types.Operator):
    bl_idname = "rr.sqe_isolate_strip_exit"
    bl_label = "Exit isolate strip view"
    bl_description = "Exits isolate strip view and restores previous state"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: bpy.types.Context) -> Set[str]:

        for i in context.scene.rr.isolate_view:
            try:
                strip = context.scene.sequence_editor.sequences[i.name]
            except KeyError:
                logger.error("Exit isolate view: Strip does not exist %s", i.name)
                continue

            strip.mute = i.mute

        # Clear all items.
        context.scene.rr.isolate_view.clear()

        return {"FINISHED"}


class RR_OT_sqe_isolate_strip_enter(bpy.types.Operator):
    bl_idname = "rr.sqe_isolate_strip_enter"
    bl_label = "Isolate Strip"
    bl_description = "Isolate all selected sequence strips, others are hidden. Previous state is saved and restorable"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        active_strip = context.scene.sequence_editor.active_strip
        return bool(active_strip)

    def execute(self, context: bpy.types.Context) -> Set[str]:

        sequences = list(context.scene.sequence_editor.sequences_all)

        if context.scene.rr.isolate_view.items():
            bpy.ops.rr.sqe_isolate_strip_exit()

        # Mute all and save state to restore later.
        for s in sequences:
            # Save this state to restore it later.
            item = context.scene.rr.isolate_view.add()
            item.name = s.name
            item.mute = s.mute
            s.mute = True

        # Unmute selected.
        for s in context.selected_sequences:
            s.mute = False

        return {"FINISHED"}


class RR_OT_sqe_push_to_edit(bpy.types.Operator):
    """
    This operator pushes the active render strip to the edit. Only .mp4 files will be pushed to edit.
    If the .mp4 file is not existent but the preview .jpg sequence is in the render folder. This operator
    creates an .mp4 with ffmpeg. The .mp4 file will be named after the flamenco naming convention, but when
    copied over to the Shot Previews it will be renamed and gets a version string.
    """

    bl_idname = "rr.sqe_push_to_edit"
    bl_label = "Push to edit"
    bl_description = (
        "Copies .mp4 file of current sequence strip to the shot preview directory with"
        "auto version incrementation."
        "Creates .mp4 with ffmpeg if not existent yet"
    )

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        addon_prefs = prefs.addon_prefs_get(context)
        if not addon_prefs.shot_previews_path:
            return False

        active_strip = context.scene.sequence_editor.active_strip
        return bool(
            active_strip and active_strip.type == "IMAGE" and active_strip.rr.is_render
        )

    def execute(self, context: bpy.types.Context) -> Set[str]:
        active_strip = context.scene.sequence_editor.active_strip

        render_dir = Path(bpy.path.abspath(active_strip.directory))
        shot_previews_dir = Path(opsdata.get_shot_previews_path(active_strip))
        shot_name = shot_previews_dir.parent.name
        metadata_path = shot_previews_dir / "metadata.json"

        # -------------GET MP4 OR CREATE WITH FFMPEG ---------------
        # try to get render_mp4_path will throw error if no jpg files are available
        try:
            mp4_path = Path(opsdata.get_farm_output_mp4_path(active_strip))
        except NoImageSequenceAvailableException:
            # No jpeg files available.
            self.report(
                {"ERROR"}, f"No preview files available in {render_dir.as_posix()}"
            )
            return {"CANCELLED"}

        # If mp4 path does not exists use ffmpeg to create preview file.
        if not mp4_path.exists():
            preview_files = opsdata.get_best_preview_sequence(render_dir)
            fffmpeg_command = f"ffmpeg -start_number {int(preview_files[0].stem)} -framerate {vars.FPS} -i {render_dir.as_posix()}/%06d{preview_files[0].suffix} -c:v libx264 -preset medium -crf 23 -pix_fmt yuv420p {mp4_path.as_posix()}"
            logger.info("Creating .mp4 with ffmpeg")
            subprocess.call(fffmpeg_command, shell=True)
            logger.info("Created .mp4: %s", mp4_path.as_posix())
        else:
            logger.info("Found existing .mp4 file: %s", mp4_path.as_posix())

        # --------------COPY MP4 TO Shot Previews ----------------.

        # Create edit path if not exists yet.
        if not shot_previews_dir.exists():
            shot_previews_dir.mkdir(parents=True)
            logger.info(
                "Created dir in Shot Previews: %s", shot_previews_dir.as_posix()
            )

        # Get edit_filepath.
        edit_filepath = self.get_edit_filepath(active_strip)

        # Copy mp4 to edit filepath.
        shutil.copy2(mp4_path.as_posix(), edit_filepath.as_posix())
        logger.info(
            "Copied: %s \nTo: %s", mp4_path.as_posix(), edit_filepath.as_posix()
        )

        # ----------------UPDATE METADATA.JSON ------------------.

        # Create metadata json.
        if not metadata_path.exists():
            metadata_path.touch()
            logger.info("Created metadata.json: %s", metadata_path.as_posix())
            opsdata.save_to_json({}, metadata_path)

        # Udpate metadata json.
        json_obj = opsdata.load_json(metadata_path)
        json_obj[edit_filepath.name] = mp4_path.as_posix()
        opsdata.save_to_json(
            json_obj,
            metadata_path,
        )
        logger.info("Updated metadata in: %s", metadata_path.as_posix())

        # Log.
        self.report(
            {"INFO"},
            f"Pushed to edit: {edit_filepath.as_posix()}",
        )
        return {"FINISHED"}

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        active_strip = context.scene.sequence_editor.active_strip
        edit_filepath = self.get_edit_filepath(active_strip)

        try:
            mp4_path = Path(opsdata.get_farm_output_mp4_path(active_strip))
        except NoImageSequenceAvailableException:
            layout.separator()
            layout.row(align=True).label(
                text="No preview files available", icon="ERROR"
            )
            return

        text = "From Farm Output:"
        if not mp4_path.exists():
            text = "From Farm Output (will be created with ffmpeg):"

        layout.separator()
        layout.row(align=True).label(text=text, icon="RENDER_ANIMATION")
        layout.row(align=True).label(text=mp4_path.as_posix())

        layout.separator()
        layout.row(align=True).label(text="To Shot Previews:", icon="FILE_TICK")
        layout.row(align=True).label(text=edit_filepath.as_posix())

        layout.separator()
        layout.row(align=True).label(text="Copy to Shot Previews?")

    def invoke(self, context, event):
        active_strip = context.scene.sequence_editor.active_strip
        try:
            mp4_path = Path(opsdata.get_farm_output_mp4_path(active_strip))
        except NoImageSequenceAvailableException:
            width = 200
        else:
            width = 200 + len(mp4_path.as_posix()) * 5
        return context.window_manager.invoke_props_dialog(self, width=width)

    def get_edit_filepath(self, strip: bpy.types.ImageSequence) -> Path:
        render_dir = Path(bpy.path.abspath(strip.directory))
        shot_previews_dir = Path(opsdata.get_shot_previews_path(strip))

        # Find latest edit version.
        existing_files: List[Path] = []
        increment = "v001"
        if shot_previews_dir.exists():
            for file in shot_previews_dir.iterdir():
                if not file.is_file():
                    continue

                if not file.name.startswith(opsdata.get_shot_dot_task_type(render_dir)):
                    continue

                version = util.get_version(file.name)
                if not version:
                    continue

                if (
                    file.name.replace(version, "")
                    == f"{opsdata.get_shot_dot_task_type(render_dir)}..mp4"
                ):
                    existing_files.append(file)

            existing_files.sort(key=lambda f: f.name)

            # Get version string.
            if len(existing_files) > 0:
                latest_version = util.get_version(existing_files[-1].name)
                increment = "v{:03}".format(int(latest_version.replace("v", "")) + 1)

        # Compose edit filepath of new mp4 file.
        edit_filepath = (
            shot_previews_dir
            / f"{opsdata.get_shot_dot_task_type(render_dir)}.{increment}.mp4"
        )
        return edit_filepath


# ----------------REGISTER--------------.


classes = [
    RR_OT_sqe_create_review_session,
    RR_OT_setup_review_workspace,
    RR_OT_sqe_inspect_exr_sequence,
    RR_OT_sqe_clear_exr_inspect,
    RR_OT_sqe_approve_render,
    RR_OT_sqe_update_is_approved,
    RR_OT_open_path,
    RR_OT_sqe_isolate_strip_enter,
    RR_OT_sqe_isolate_strip_exit,
    RR_OT_sqe_push_to_edit,
]

addon_keymap_items = []


def register():

    for cls in classes:
        bpy.utils.register_class(cls)

    # register hotkeys
    # does not work if blender runs in background
    if not bpy.app.background:
        global addon_keymap_items
        keymap = bpy.context.window_manager.keyconfigs.addon.keymaps.new(name="Window")

        # Isolate strip.
        addon_keymap_items.append(
            keymap.keymap_items.new(
                "rr.sqe_isolate_strip_enter", value="PRESS", type="ONE"
            )
        )

        # Umute all.
        addon_keymap_items.append(
            keymap.keymap_items.new(
                "rr.sqe_isolate_strip_exit", value="PRESS", type="ONE", alt=True
            )
        )
        for kmi in addon_keymap_items:
            logger.info(
                "Registered new hotkey: %s : %s", kmi.type, kmi.properties.bl_rna.name
            )


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

    # Does not work if blender runs in background.
    if not bpy.app.background:
        global addon_keymap_items
        # Remove hotkeys.
        keymap = bpy.context.window_manager.keyconfigs.addon.keymaps["Window"]
        for kmi in addon_keymap_items:
            logger.info("Remove  hotkey: %s : %s", kmi.type, kmi.properties.bl_rna.name)
            keymap.keymap_items.remove(kmi)

        addon_keymap_items.clear()
