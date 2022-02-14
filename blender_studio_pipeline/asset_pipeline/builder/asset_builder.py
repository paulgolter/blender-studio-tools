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
import pickle
import logging

from typing import List, Dict, Union, Any, Set, Optional, Tuple
from pathlib import Path

import bpy

from .context import ProductionContext, AssetContext, BuildContext
from .blstarter import BuilderBlenderStarter

logger = logging.getLogger("BSP")


class AssetBuilderFailedToInitialize(Exception):
    pass


class AssetBuilder:
    def __init__(self, build_context: BuildContext):
        if not build_context:
            raise AssetBuilderFailedToInitialize(
                "Failed to initialize AssetBuilder. Build_context not valid."
            )

        self._build_context = build_context

    @property
    def build_context(self) -> BuildContext:
        return self._build_context

    def publish(self) -> None:
        # Catch special case first version.
        if not self.build_context._asset_publishes:
            self._create_first_version()
            return

        # Normal publish process.

        # No here it gets a little tricky. We cannot just simply
        # perform a libraries.write() operation. The merge process
        # requires additional operations to happen so we need to actually
        # open the asset version blend file and perform them.

        # Now we already assembled this huge BuildContext, in which we have
        # all the information we need for whatever needs to be done.
        # The question is how can we share this info with the new Blender Instance
        # that knows nothing about it.

        # A very effective and easy ways seems to be pickling the BuildContext
        # and unpickling  it in the new Blender Instance again.
        # Some objects cannot be pickled (like the blender context or a collection)
        # (We can add custom behavior to work around this please see: ./context.py)

        # Start pickling.
        pickle_path = self.build_context.asset_task.pickle_path
        with open(pickle_path.as_posix(), "wb") as f:
            pickle.dump(self.build_context, f)
        logger.info(f"Pickled to {pickle_path.as_posix()}")

        # Open new blender instance, with publish script.

        # Tmp, use first version, TODO: for all elements in process_pairs
        BuilderBlenderStarter.start_publish(
            self.build_context.asset_publishes[0].path,
            pickle_path,
        )

    def pull(self) -> None:
        # TODO:
        return

    def _create_first_version(self) -> None:
        target = self._build_context.asset_dir.get_first_publish_path()
        asset_coll = self._build_context.asset_context.asset_collection
        # with bpy.data.libraries.load(target.as_posix(), relative=True, link=False) as (
        #     data_from,
        #     data_to,
        # ):
        #     data_to.collections.append(asset_coll.name)
        data_blocks = set((asset_coll,))

        # Create directory if not exist.
        target.parent.mkdir(parents=True, exist_ok=True)

        bpy.data.libraries.write(
            target.as_posix(), data_blocks, path_remap="RELATIVE_ALL", fake_user=True
        )
        logger.info("Created first asset version: %s", target.as_posix())
