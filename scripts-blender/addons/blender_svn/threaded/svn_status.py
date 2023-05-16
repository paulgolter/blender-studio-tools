# SPDX-License-Identifier: GPL-2.0-or-later
# (c) 2022, Blender Foundation - Demeter Dzadik

from .. import wheels
# This will load the xmltodict wheel file.
wheels.preload_dependencies()

import bpy
from bpy.props import StringProperty
from typing import List, Dict, Union, Any, Set, Optional, Tuple

from pathlib import Path
from datetime import datetime
import xmltodict
import subprocess

from .background_process import BackgroundProcess, Processes
from .execute_subprocess import execute_svn_command, execute_command
from .. import constants
from ..util import get_addon_prefs, redraw_viewport
from . import svn_log


class SVN_OT_explain_status(bpy.types.Operator):
    bl_idname = "svn.explain_status"
    bl_label = ""  # Don't want the first line of the tooltip on mouse hover.
    bl_description = "Show an explanation of this status, using a dynamic tooltip"
    bl_options = {'INTERNAL'}

    status: StringProperty(
        description="Identifier of the status to show an explanation for"
    )
    file_rel_path: StringProperty(
        description="Path of the file to select in the list when clicking this explanation, to act as if it was click-through-able"
    )

    @staticmethod
    def get_explanation(status: str):
        return constants.SVN_STATUS_DATA[status][1]

    @classmethod
    def description(cls, context, properties):
        return cls.get_explanation(properties.status)

    def draw(self, context):
        self.layout.label(text=self.get_explanation(self.status))

    def execute(self, context):
        """Set the index on click, to act as if this operator button was 
        click-through in the UIList."""
        if not self.file_rel_path:
            return {'FINISHED'}
        repo = context.scene.svn.get_repo(context)
        file_entry = repo.get_file_by_svn_path(self.file_rel_path)
        file_entry_idx = repo.get_index_of_file(file_entry)
        repo.external_files_active_index = file_entry_idx
        return {'FINISHED'}


def get_svn_info(context, dirpath: Path) -> Optional[str]:
    try:
        path = dirpath.as_posix()
        return execute_command(path, ["svn", "info"])
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.decode()
        if "is not a working copy" in error_msg:
            return
        elif "E200009" in error_msg:
            # If we're in a folder that wasn't yet added to the repo,
            # try again one folder higher.
            parent = dirpath.parent
            if parent == dirpath:
                return
            return get_svn_info(context, dirpath.parent)
        else:
            raise e


def set_scene_svn_info(context) -> bool:
    """Check if the current .blend file is in an SVN repository.
    If it is, use `svn info` to grab the SVN URL and directory and store them in the Scene.

    The rest of the add-on will use this stored URL & Dir to find the corresponding 
    SVN repository data stored in the user preferences.

    Returns whether initialization was successful or not.
    """
    scene_svn = context.scene.svn
    scene_svn.svn_url = ""

    dirpath = Path(bpy.data.filepath).parent
    svn_info = get_svn_info(context, dirpath)
    if not svn_info:
        return False

    lines = svn_info.split("\n")
    dir_path = lines[1].split("Working Copy Root Path: ")[1]
    # On Windows, for some reason the path has a \r character at the end,
    # which breaks absolutely everything.
    dir_path = dir_path.replace("\r", "")
    scene_svn.svn_directory = dir_path

    full_url = lines[2].split("URL: ")[1]
    relative_url = lines[3].split("Relative URL: ")[1][1:]
    base_url = full_url.replace(relative_url, "")
    scene_svn.svn_url = base_url
    return True


@bpy.app.handlers.persistent
def init_svn_info(_scene=None):
    """Initialize SVN info and authenticate when opening a .blend file."""

    context = bpy.context
    scene_svn = context.scene.svn

    prefs = get_addon_prefs(context)
    prefs.load_repo_info_from_file()

    if not bpy.data.filepath:
        scene_svn.svn_url = ""
        return

    repo = prefs.get_current_repo(context)
    in_repo = set_scene_svn_info(context)
    if not in_repo:
        if repo:
            repo.external_files.clear()
            repo.log.clear()
        return

    if not repo:
        repo = prefs.svn_repositories.add()
        repo.url = scene_svn.svn_url
        repo.directory = scene_svn.svn_directory
        repo.display_name = Path(scene_svn.svn_directory).name

    prefs.is_busy = False

    if repo.external_files_active_index > len(repo.external_files):
        repo.external_files_active_index = 0
    repo.log_active_index = len(repo.log)-1

    repo.reload_svn_log(context)

    if repo.is_cred_entered:
        repo.authenticate(context)

################################################################################
############## AUTOMATICALLY KEEPING FILE STATUSES UP TO DATE ##################
################################################################################

class BGP_SVN_Status(BackgroundProcess):
    name = "Status"
    needs_authentication = True
    timeout = 10
    repeat_delay = 15
    debug = False

    def acquire_output(self, context, prefs):
        try:
            svn_status_str = execute_svn_command(
                context, 
                ["svn", "status", "--show-updates", "--verbose", "--xml"],
                use_cred=True
            )
            self.output = get_repo_file_statuses(svn_status_str)
        except subprocess.CalledProcessError as error:
            # TODO: If this is an authentication error, we should set repo.authenticated=False.
            # This could happen if the user's password has changed while Blender was running.
            self.error = error.stderr.decode()

    def process_output(self, context, prefs):
        update_file_list(context, self.output)

    def get_ui_message(self, context):
        # Calculate time since last status update
        repo = context.scene.svn.get_repo(context)
        if repo.seconds_since_last_update > 30:
            return "Updating file statuses..."


class BGP_SVN_Authenticate(BGP_SVN_Status):
    name = "Authenticate"
    needs_authentication = False
    timeout = 10
    repeat_delay = 0
    debug = False

    def tick(self, context, prefs):
        redraw_viewport()

    def acquire_output(self, context, prefs):
        repo = prefs.get_current_repo(context)
        if not repo or not repo.is_cred_entered:
            return

        super().acquire_output(context, prefs)

    def process_output(self, context, prefs):
        repo = prefs.get_current_repo(context)
        if not repo or not repo.is_cred_entered:
            return

        if self.output:
            repo.authenticated = True
            repo.auth_failed = False

            super().process_output(context, prefs)
            Processes.start('Status')
            Processes.start('Log')
            return
        elif self.error:
            if "Authentication failed" in self.error:
                repo.authenticated = False
                repo.auth_failed = True
            else:
                repo.authenticated = False
                repo.auth_failed = False

def update_file_list(context, file_statuses: Dict[str, Tuple[str, str, int]]):
    """Update the file list based on data from get_svn_file_statuses().
    (See timer_update_svn_status)"""
    scene_svn = context.scene.svn
    repo = scene_svn.get_repo(context)
    repo.timestamp_last_status_update = datetime.strftime(
        datetime.now(), "%Y/%m/%d %H:%M:%S")

    svn_paths = []
    new_files_on_repo = set()
    for filepath_str, status_info in file_statuses.items():
        svn_path = Path(filepath_str)
        svn_path_str = str(svn_path.as_posix())
        suffix = svn_path.suffix
        if (suffix.startswith(".r") and suffix[2:].isdecimal()) \
                or (suffix.startswith(".blend") and suffix[6:].isdecimal()) \
                or suffix.endswith("blend@"):
            # Do not add certain file extensions, ever:
            # .r### files are from SVN conflicts waiting to be resolved.
            # .blend@ is the Blender filesave temp file.
            # .blend### are Blender backup files.
            continue

        svn_paths.append(svn_path_str)

        wc_status, repos_status, revision = status_info

        file_entry = repo.get_file_by_svn_path(svn_path)
        entry_existed = True
        if not file_entry:
            entry_existed = False
            file_entry = repo.external_files.add()
            file_entry.svn_path = svn_path_str
            file_entry.absolute_path = str(repo.svn_to_absolute_path(svn_path).as_posix())

            file_entry['name'] = svn_path.name
            if not file_entry.exists:
                new_files_on_repo.add((file_entry.svn_path, repos_status))

        if file_entry.status_predicted_flag == 'SINGLE':
            # File status was predicted by a local svn file operation,
            # so we should ignore this status update and reset the flag.
            # The file status will be updated on the next status update.
            # This is because this status update was initiated before the file's
            # status was predicted, so the prediction is likely to be correct,
            # and the status we have here is likely to be outdated.
            file_entry.status_predicted_flag = 'WAITING'
            continue
        elif file_entry.status_predicted_flag not in {'NONE', 'WAITING'}:
            # We wait for `svn up/commit` background processes to finish and
            # set the predicted flag to SINGLE. Until then, we ignore status
            # updates on files that are being updated or committed.
            continue

        if entry_existed and (file_entry.repos_status == 'none' and repos_status != 'none'):
            new_files_on_repo.add((file_entry.svn_path, repos_status))

        file_entry.revision = revision
        file_entry.status = wc_status
        file_entry.repos_status = repos_status
        file_entry.status_predicted_flag = 'NONE'

    if new_files_on_repo:
        # File entry status has changed between local and repo.
        file_strings = []
        for svn_path, repos_status in new_files_on_repo:
            status_char = constants.SVN_STATUS_NAME_TO_CHAR.get(repos_status, " ")
            file_strings.append(f"{status_char}    {svn_path}")
        print(
            "SVN: Detected file changes on remote:\n",
            "\n".join(file_strings),
            "\nUpdating log...\n"
        )
        Processes.start('Log')

    # Remove file entries who no longer seem to have an SVN status.
    # This can happen if an unversioned file was removed from the filesystem,
    # Or sub-folders whose parent was Un-Added to the SVN.
    for file_entry in repo.external_files[:]:
        if file_entry.svn_path not in svn_paths:
            repo.remove_file_entry(file_entry)

    scene_svn.force_good_active_index(context)

def get_repo_file_statuses(svn_status_str: str) -> Dict[str, Tuple[str, str, int]]:
    svn_status_xml = xmltodict.parse(svn_status_str)
    file_infos = svn_status_xml['status']['target']['entry']
    # print(json.dumps(file_infos, indent=4))

    file_statuses = {}
    for file_info in file_infos:
        filepath = file_info['@path']

        repos_status = "none"
        if 'repos-status' in file_info:
            repos_status_block = file_info['repos-status']
            repos_status = repos_status_block['@item']
            _repo_props = repos_status_block['@props']
        # else:
            # TODO: I commented this out for now, but it may be a necessary optimization
            # if Blender starts stuttering due to the SVN status updates.
            # continue

        wc_status_block = file_info.get('wc-status')
        wc_status = wc_status_block['@item']
        _revision = int(wc_status_block.get('@revision', 0))
        _props = wc_status_block['@props']

        if 'commit' in wc_status_block:
            commit_block = wc_status_block['commit']
            commit_revision = int(commit_block['@revision'])
            _commit_author = commit_block['author']
            _commit_date = commit_block['date']
        else:
            commit_revision = 0

        file_statuses[filepath] = (wc_status, repos_status, commit_revision)

    return file_statuses


@bpy.app.handlers.persistent
def mark_current_file_as_modified(_dummy1=None, _dummy2=None):
    context = bpy.context
    scene_svn = context.scene.svn
    if not scene_svn.svn_directory:
        return
    current_blend = scene_svn.get_repo(context).current_blend_file
    if current_blend:
        current_blend.status = 'modified'
        current_blend.status_predicted_flag = 'SINGLE'


################################################################################
############################# REGISTER #########################################
################################################################################

def delayed_init_svn(delay=1):
    bpy.app.timers.register(init_svn_info, first_interval=delay)

def register():
    bpy.app.handlers.load_post.append(init_svn_info)

    bpy.app.handlers.save_post.append(init_svn_info)
    bpy.app.handlers.save_post.append(mark_current_file_as_modified)

    delayed_init_svn()

def unregister():
    bpy.app.handlers.load_post.remove(init_svn_info)

    bpy.app.handlers.save_post.remove(init_svn_info)
    bpy.app.handlers.save_post.remove(mark_current_file_as_modified)


registry = [SVN_OT_explain_status]
