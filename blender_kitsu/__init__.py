import bpy
from blender_kitsu import (
    rdpreset,
    bkglobals,
    types,
    cache,
    models,
    propsdata,
    props,
    prefs,
    sqe,
    ops_generic_data,
    ops_generic,
    ops_auth,
    ops_context_data,
    ops_context,
    anim,
    ui,
)

from blender_kitsu.logger import ZLoggerFactory, ZLoggerLevelManager

logger = ZLoggerFactory.getLogger(__name__)

bl_info = {
    "name": "Blender Kitsu",
    "author": "Paul Golter",
    "description": "Blender addon to interact with Kitsu",
    "blender": (2, 93, 0),
    "version": (0, 1, 0),
    "location": "View3D",
    "warning": "",
    "doc_url": "",
    "tracker_url": "",
    "category": "Generic",
}

_need_reload = "props" in locals()

if _need_reload:
    import importlib

    logger.info("-START- Reloading blender-kitsu")

    rdpreset.reload()
    bkglobals = importlib.reload(bkglobals)
    cache = importlib.reload(cache)
    types = importlib.reload(types)
    models = importlib.reload(models)
    propsdata = importlib.reload(propsdata)
    props = importlib.reload(props)
    prefs = importlib.reload(prefs)
    sqe.reload()
    ops_generic_data = importlib.reload(ops_generic_data)
    ops_generic = importlib.reload(ops_generic)
    ops_auth = importlib.reload(ops_auth)
    ops_context_data = importlib.reload(ops_context_data)
    ops_context = importlib.reload(ops_context)
    anim.reload()
    ui = importlib.reload(ui)

    ZLoggerLevelManager.configure_levels()
    logger.info("-END- Reloading blender-kitsu")


def register():
    logger.info("-START- Registering blender-kitsu")

    rdpreset.register()
    prefs.register()
    cache.register()
    props.register()
    sqe.register()
    ops_generic.register()
    ops_auth.register()
    ops_context.register()
    anim.register()
    ui.register()

    ZLoggerLevelManager.configure_levels()
    logger.info("-END- Registering blender-kitsu")


def unregister():
    logger.info("-START- Unregistering blender-kitsu")

    ui.unregister()
    anim.unregister()
    ops_context.unregister()
    ops_auth.unregister()
    ops_generic.unregister()
    sqe.unregister()
    props.unregister()
    cache.unregister()
    prefs.unregister()
    rdpreset.unregister()

    ZLoggerLevelManager.restore_levels()
    logger.info("-END- Unregistering blender-kitsu")


if __name__ == "__main__":
    register()
