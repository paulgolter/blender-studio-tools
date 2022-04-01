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
# (c) 2022, Blender Foundation - Demeter Dzadik

from typing import List, Dict, Union, Any, Set, Optional, Tuple
from pathlib import Path
from datetime import datetime

import bpy
from bpy.props import IntProperty, StringProperty
from .util import get_addon_prefs, make_getter_func, make_setter_func_readonly

from . import client
from .ops import SVN_Operator_Single_File

class SVN_log(bpy.types.PropertyGroup):
    """Property Group that can represent an SVN log entry."""

    revision_number: IntProperty(
        name="Revision Number",
        description="Revision number of the current .blend file",
        get = make_getter_func("revision_number", 0),
        set = make_setter_func_readonly("revision_number")
    )
    revision_date: StringProperty(
        name="Revision Date",
        description="Date when the current revision was committed",
        get = make_getter_func("revision_date", ""),
        set = make_setter_func_readonly("revision_date")
    )
    revision_author: StringProperty(
        name="Revision Author",
        description="SVN username of the revision author",
        get = make_getter_func("revision_author", ""),
        set = make_setter_func_readonly("revision_author")
    )
    commit_message: StringProperty(
        name = "Commit Message",
        description="Commit message written by the commit author to describe the changes in this revision",
        get = make_getter_func("commit_message", ""),
        set = make_setter_func_readonly("commit_message")
    )


def layout_log_split(layout):
    main = layout.split(factor=0.2)
    num_and_auth = main.row()
    date_and_msg = main.row()
    
    num_and_auth_split = num_and_auth.split(factor=0.3)
    num = num_and_auth_split.row()
    auth = num_and_auth_split.row()

    date_and_msg_split = date_and_msg.split(factor=0.2)
    date = date_and_msg_split.row()
    msg = date_and_msg_split.row()

    return num, auth, date, msg


class SVN_UL_log(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        if self.layout_type != 'DEFAULT':
            raise NotImplemented
        
        log_entry = item

        num, auth, date, msg = layout_log_split(layout.row())

        num.label(text=str(log_entry.revision_number))
        auth.label(text=log_entry.revision_author)
        date.label(text=log_entry.revision_date.split(" ")[0][5:])

        commit_msg = log_entry.commit_message
        commit_msg = commit_msg[:60]+".." if len(commit_msg) > 62 else commit_msg
        msg.label(text=commit_msg)


class VIEW3D_PT_svn_log(bpy.types.Panel):
    """Display the revision history of the selected file."""
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'SVN'
    bl_label = 'Revision History'
    bl_parent_id = "VIEW3D_PT_svn_files"

    @classmethod
    def poll(cls, context):
        return len(context.scene.svn.log) > 0

    def draw(self, context):
        # TODO: SVN log only makes sense for files with certain statuses (eg., not "Unversioned")
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        num, auth, date, msg = layout_log_split(layout.row())
        num.label(text="r#")
        auth.label(text="Author")
        date.label(text="Date")
        msg.label(text="Message")
        layout.template_list(
            "SVN_UL_log",
            "svn_log",
            context.scene.svn,
            "log",
            context.scene.svn,
            "log_active_index",
        )

        active_log = context.scene.svn.log[context.scene.svn.log_active_index]
        layout.prop(active_log, 'revision_number')
        layout.prop(active_log, 'revision_date')
        layout.prop(active_log, 'revision_author')


def update_svn_log_data(context, filepath: Path):
    """Read the svn.log file (written by this addon) into the log entry list."""

    svn = context.scene.svn
    svn.log.clear()

    # Read file into lists of lines where each list is one log entry
    chunks = []
    with open(filepath, 'r') as f:
        next(f)
        chunk = []
        for line in f:
            line = line.replace("\n", "")
            if len(line) == 0:
                continue
            if line == "-" * 72:
                # The previous log entry is over.
                chunks.append(chunk)
                chunk = []
                continue
            chunk.append(line)

    for chunk in chunks:
        r_number, r_author, r_date, _r_msg_length = chunk[0].split(" | ")
        date, time, timezone, _day, _n_day, _mo, _y = r_date.split(" ")

        log_entry = svn.log.add()
        log_entry['revision_number'] = int(r_number[1:])
        log_entry['revision_author'] = r_author

        rev_datetime = datetime.strptime(date +" "+ time, '%Y-%m-%d %H:%M:%S')
        month_name = rev_datetime.strftime("%b")
        date_str = f"{rev_datetime.year}-{month_name}-{rev_datetime.day}"
        time_str = f"{str(rev_datetime.hour).zfill(2)}:{str(rev_datetime.minute).zfill(2)}"

        log_entry['revision_date'] = date_str + " " + time_str
        log_entry['commit_message'] = "\n".join(chunk[1:])


class SVN_update_log(SVN_Operator_Single_File, bpy.types.Operator):
    bl_idname = "svn.update_log"
    bl_label = "Update SVN Log"
    bl_description = "Update the SVN Log file with new log entries grabbed from the remote repository"
    bl_options = {'INTERNAL'}

    missing_file_allowed = True

    # TODO: This is a good start, but if we want this to passively stay up to 
    # date for everyone, we can't just have everybody updating their log file 
    # and committing it, it will create conflicts constantly. 

    # Idea 1: The SVN Commit operator would always update the log file, write 
    # the commit that's about to happen into it, and then include it in the commit. 
    # So, absolutely every commit to the SVN will include the log file as well.
    # Might work, but seems tricky.

    # Idea 2: We store the commit log in the .svn folder, which is ignored by svn,
    # and we update it when running the SVN Update operator, making it a bit slower.

    def execute(self, context):
        # Create the log file if it doesn't already exist.
        self.file_rel_path = ".svn/svn.log"
        filepath = self.get_file_full_path(context)

        if filepath.exists():
            update_svn_log_data(context, filepath)

        return {'FINISHED'}

        prefs = get_addon_prefs(context)
        current_rev = prefs.revision_number
        latest_log_rev = svn.log[-1].revision_number

        new_log = self.execute_svn_command(context, f"svn log -r {latest_log_rev}:{current_rev}")

        with open(filepath, 'w+') as f:
            f.write(new_log)

        self.report({'INFO'}, "Local copy of the SVN log updated.")

        return {'FINISHED'}


registry = [SVN_log, VIEW3D_PT_svn_log, SVN_UL_log, SVN_update_log]
