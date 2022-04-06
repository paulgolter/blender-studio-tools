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
# (c) 2022, Blender Foundation - Demeter Dzadik

from typing import Optional, Dict, Any, List, Tuple, Set

from collections import OrderedDict
from pathlib import Path

from blender_svn.util import get_addon_prefs

import bpy, logging
from bpy.props import BoolProperty

from . import wheels
# This will load the dateutil and svn wheel file.
wheels.preload_dependencies()

from . import prefs
from .svn_log import SVN_log, SVN_file, reload_svn_log
from .svn_status import get_file_statuses

from blender_asset_tracer import trace

logger = logging.getLogger("SVN")


class SVN_scene_properties(bpy.types.PropertyGroup):
    """Scene Properties for SVN"""

    @staticmethod
    def get_referenced_filepaths() -> Set[Path]:
        """Return a flat list of absolute filepaths of existing files referenced
        either directly or indirectly by this .blend file, as a flat list.

        This uses the Blender Asset Tracer, so we rely on that to catch everything;
        Images, video files, mesh sequence caches, blender libraries, etc.

        Deleted files are not handled here; They are grabbed with PySVN instead, 
        for the entire repository. The returned list also does not include the 
        currently opened .blend file itself.
        """
        if not bpy.data.filepath:
            return set()

        bpath = Path(bpy.data.filepath)
        assert bpath.is_file(), f"{bpy.data.filepath!r} is not a file"

        reported_assets: Set[Path] = set()

        for usage in trace.deps(bpath):
            for assetpath in usage.files():
                if assetpath in reported_assets:
                    logger.debug("Already reported %s", assetpath)
                    continue

                reported_assets.add(assetpath)

        return reported_assets

    def update_outdated_file_entries(self):
        """Update all files with the 'none' status, which signified that a file 
        had a newer version available on the remote repository.
        Running this function means that this file's up-to-date-ness has been 
        ensured, and this function is just to indicate this in the UI."""
        for i, file_entry in reversed(list(enumerate(self.external_files))):
            if file_entry.status == "none":
                file_entry.status = 'normal'
                file_entry.revision = self.get_latest_revision_of_file(file_entry.svn_path)
            file_entry.newer_on_remote = False

    def remove_by_svn_path(self, path_to_remove: str):
        """Remove a file entry from the file list, based on its filepath."""
        for i, file_entry in enumerate(self.external_files):
            filepath = file_entry.svn_path
            if filepath == path_to_remove:
                self.external_files.remove(i)
                return

    def check_for_local_changes(self) -> None:
        """Update the status of file entries by checking for changes in the
        local repository."""

        context = bpy.context
        addon_prefs = get_addon_prefs(context)

        if not addon_prefs.is_in_repo:
            return

        # Remove unversioned files from the list. The ones that are still around
        #  will be re-discovered below, through get_file_statuses.
        for i, file_entry in reversed(list(enumerate(self.external_files))):
            if file_entry.status == "unversioned":
                self.external_files.remove(i)

        referenced_files: Set[Path] = self.get_referenced_filepaths()
        referenced_files.add(bpy.data.filepath)

        # {filepath : (status. revision)}, via `svn status --verbose --xml`
        file_statuses = get_file_statuses(addon_prefs.svn_directory)

        # Add file entries that are referenced by this .blend file,
        # even if the file's status is normal (un-modified)
        for referenced_file in referenced_files:
            svn_path = self.absolute_to_svn_path(referenced_file)
            status = (
                "normal",
                0,
            )  # TODO: We currently don't show a revision number for Normal status files!
            if str(svn_path) in file_statuses:
                status = file_statuses[str(svn_path)]
                del file_statuses[str(svn_path)]
            file_entry = self.add_file_entry(Path(svn_path), status[0], status[1], is_referenced=True)

        # Add file entries in the entire SVN repository for files whose status isn't
        # normal. Do this even for files not referenced by this .blend file.
        for svn_path in file_statuses.keys():
            status = file_statuses[svn_path]
            file_entry = self.add_file_entry(Path(svn_path), status[0], status[1])
        
        prefs.force_good_active_index(context)

    @staticmethod
    def absolute_to_svn_path(absolute_path: Path) -> Path:
        if type(absolute_path) == str:
            absolute_path = Path(absolute_path)
        prefs = get_addon_prefs(bpy.context)
        svn_dir = Path(prefs.svn_directory)
        return absolute_path.relative_to(svn_dir)

    def add_file_entry(
        self, svn_path: Path, status: str, rev: int, is_referenced=False
    ) -> SVN_file:
        if svn_path.suffix.startswith(".r") and svn_path.suffix[2:].isdecimal():
            # Do not add .r### files to the file list, ever.
            return
        tup = self.get_file_by_svn_path(str(svn_path))
        existed = False
        if not tup:
            item = self.external_files.add()
        else:
            existed = True
            _idx, item = tup

        # Set collection property.
        item['svn_path'] = str(svn_path)
        item['name'] = svn_path.name

        assert rev > 0 or status in ['unversioned', 'added'], "Revision number of a versioned file must be greater than 0."
        item['revision'] = rev

        if rev < self.get_latest_revision_of_file(svn_path) and status == 'normal':
            # Strange case 1: We checked out an older version of a file.
            # SVN assigns this the 'normal' status instead of 'none'(Outdated)
            # which makes more sense from user POV.
            status = 'none'

        if not svn_path.is_file() and item.status == 'none' and status == 'normal':
            # Strange case 2: A previous `svn status --verbose --show-updates`
            # marked a folder as being outdated, but a subsequent `svn status --verbose`
            # reports the status of this folder as normal. In this case, it feels more
            # accurate to keep the folder on outdated.
            # TODO: Updating an outdated folder doesn't mark the outdated files as no longer being outdated. Maybe folders shouldn't even be displayed in the UIList, I don't even really get why svn marks the folder path as modified.
            status = 'none'

        item.status = status

        # Prevent editing values in the UI.
        item['is_referenced'] = is_referenced
        return item

    def get_file_by_svn_path(self, svn_path: str) -> Tuple[int, SVN_file]:
        for i, file in enumerate(self.external_files):
            if file.svn_path == svn_path:
                return i, file

    external_files: bpy.props.CollectionProperty(type=SVN_file)  # type: ignore
    external_files_active_index: bpy.props.IntProperty()

    def get_log_by_revision(self, revision: int) -> Tuple[int, SVN_log]:
        for i, log in enumerate(self.log):
            if log.revision_number == revision:
                return i, log

    def get_latest_revision_of_file(self, svn_path: str) -> int:
        ret = 0
        for log in self.log:
            for changed_file in log.changed_files:
                if changed_file.svn_path == "/"+str(svn_path):
                    ret = log.revision_number
        return ret

    def is_file_outdated(self, file: SVN_file) -> bool:
        """A file may have the 'modified' state while also being outdated.
        In this case SVN is of no use, we need to detect and handle this case
        by ourselves.
        """
        latest = self.get_latest_revision_of_file(file.svn_path)
        current = file.revision
        return latest > current

    def file_exists(self, file: SVN_file) -> bool:
        context = bpy.context
        prefs = get_addon_prefs(context)
        svn_directory = Path(prefs.svn_directory)
        full_path = svn_directory.joinpath(Path(file.svn_path))
        return full_path.exists()

    reload_svn_log = reload_svn_log
    log: bpy.props.CollectionProperty(type=SVN_log)
    log_active_index: bpy.props.IntProperty()

    @property
    def active_file(self):
        return self.external_files[self.external_files_active_index]

    @property
    def active_log(self):
        return self.log[self.log_active_index]


@bpy.app.handlers.persistent
def check_for_local_changes(scene):
    if bpy.data.filepath == "":
        get_addon_prefs(bpy.context).reset()
        return
    if not scene:
        # When called from save_post() handler, which apparently does not pass anything???
        scene = bpy.context.scene
    scene.svn.check_for_local_changes()


# ----------------REGISTER--------------.

registry = [SVN_scene_properties]

def register() -> None:
    # Scene Properties.
    bpy.types.Scene.svn = bpy.props.PointerProperty(type=SVN_scene_properties)
    bpy.app.handlers.load_post.append(check_for_local_changes)
    bpy.app.handlers.save_post.append(check_for_local_changes)


def unregister() -> None:
    del bpy.types.Scene.svn
    bpy.app.handlers.load_post.remove(check_for_local_changes)
    bpy.app.handlers.save_post.remove(check_for_local_changes)
