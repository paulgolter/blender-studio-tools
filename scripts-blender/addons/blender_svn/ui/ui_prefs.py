from bpy.types import UIList

class SVN_UL_repositories(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        repo = item
        row = layout.row()
        row.label(text=repo.display_name)
        row.prop(repo, 'directory', text="")


def draw_prefs(self, context) -> None:
    layout = self.layout

    layout.prop(self, 'debug_mode')

    layout.label(text="SVN Repositories:")
    col = layout.column()
    col.template_list(
        "SVN_UL_repositories",
        "svn_repo_list",
        self,
        "repositories",
        self,
        "active_repo_idx",
    )

    if len(self.repositories) == 0:
        return
    if self.active_repo_idx-1 > len(self.repositories):
        return
    active_repo = self.repositories[self.active_repo_idx]
    if not active_repo:
        return

    layout.prop(active_repo, 'display_name', icon='FILE_TEXT')
    layout.prop(active_repo, 'url', icon='URL')
    layout.prop(active_repo, 'username', icon='USER')
    layout.prop(active_repo, 'password', icon='LOCKED')


registry = [
    SVN_UL_repositories,
]