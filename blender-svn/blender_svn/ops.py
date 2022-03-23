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

import logging

from typing import List, Dict, Union, Any, Set, Optional, Tuple
from pathlib import Path

import bpy
from bpy.app.handlers import persistent

from . import util, client, opsdata

import functools
from blender_asset_tracer import cli, trace, bpathlib

logger = logging.getLogger("SVN")

def get_referenced_filepaths() -> Set[Path]:
    """Return a flat list of files referenced either directly or indirectly
    by this .blend file, as a flat list.
    This uses the Blender Asset Tracer, so we rely on that to catch everything;
    Images, video files, mesh sequence caches, blender libraries, everything.
    """
    bpath = Path(bpy.data.filepath)

    reported_assets: Set[Path] = set()
    last_reported_bfile = None
    shorten = functools.partial(cli.common.shorten, Path.cwd())

    for usage in trace.deps(bpath):
        filepath = usage.block.bfile.filepath.absolute()
        # if filepath != last_reported_bfile:
            # print(shorten(filepath))

        last_reported_bfile = filepath

        for assetpath in usage.files():
            assetpath = bpathlib.make_absolute(assetpath)
            if assetpath in reported_assets:
                logger.debug("Already reported %s", assetpath)
                continue

            # print("   ", shorten(assetpath))
            reported_assets.add(assetpath)

    return reported_assets

class SVN_collect_dirty_files_local(bpy.types.Operator):
    bl_idname = "svn.collect_dirty_files_local"
    bl_label = "Collect Dirty Files Local"
    bl_description = (
        "Checks this .blend file and all its external references for uncommitted changes "
        "Populates a scene property with those files so they can be displayed in the UI"
    )

    def execute(self, context: bpy.types.Context) -> Set[str]:
        print("Here be all the files, courtesy of BAT:")
        files = get_referenced_filepaths()

        for f in files:
            print(f)

        # Populate context with collected asset collections.
        opsdata.populate_context_with_external_files(
            context,
        )

        # Redraw UI.
        util.redraw_ui()

        return {"FINISHED"}

# ----------------REGISTER--------------.

registry = [
    SVN_collect_dirty_files_local
]
