# SPDX-License-Identifier: GPL-2.0-or-later
# (c) 2021, Blender Foundation - Paul Golter
# (c) 2022, Blender Foundation - Demeter Dzadik

from .util import get_addon_prefs
from bpy.props import StringProperty, PointerProperty
from bpy.types import PropertyGroup
import bpy
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple, Set
from . import wheels
# This will load the dateutil and BAT wheel files.
wheels.preload_dependencies()


class SVN_scene_properties(PropertyGroup):
    """Subversion properties to match this scene to a repo in the UserPrefs"""
    svn_url: StringProperty(
        name="Remote URL",
        default="",
        description="URL of the remote SVN repository of the current file, if any. Used to match to the SVN data stored in the user preferences",
    )
    svn_directory: StringProperty(
        name="Root Directory",
        default="",
        subtype="DIR_PATH",
        description="Absolute directory path of the SVN repository's root in the file system",
    )

    def get_repo(self, context):
        """Return the current repository.
        Depending on preferences, this is either the repo the current .blend file is in, 
        or whatever repo is selected in the preferences UI.
        """
        prefs = get_addon_prefs(context)

        if prefs.active_repo_mode == 'CURRENT_BLEND':
            return self.get_scene_repo(context)
        else:
            return prefs.active_repo

    def get_scene_repo(self, context) -> Optional['SVN_repository']:
        if not self.svn_url or not self.svn_directory:
            return

        prefs = get_addon_prefs(context)
        for repo in prefs.repositories:
            if (repo.url == self.svn_url) and (Path(repo.directory) == Path(self.svn_directory)):
                return repo


registry = [
    SVN_scene_properties,
]


def register() -> None:
    # Scene Properties.
    bpy.types.Scene.svn = PointerProperty(type=SVN_scene_properties)


def unregister() -> None:
    del bpy.types.Scene.svn
