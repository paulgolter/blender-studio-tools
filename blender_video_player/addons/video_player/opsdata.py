from pathlib import Path
from typing import Tuple, List, Union, Dict

import bpy

from video_player import vars


def is_movie(filepath: Path) -> bool:
    if filepath.suffix in vars.MOVIE_EXT:
        return True
    return False


def is_image(filepath: Path) -> bool:
    if filepath.suffix in vars.IMG_EXT:
        return True
    return False


def del_all_sequences(context: bpy.types.Context) -> None:
    for seq_name in [s.name for s in context.scene.sequence_editor.sequences_all]:
        context.scene.sequence_editor.sequences.remove(
            context.scene.sequence_editor.sequences[seq_name]
        )


def fit_frame_range_to_strips(
    context: bpy.types.Context,
) -> Tuple[int, int]:
    """
    Fits frame range of active scene to exactly encapsulate all strips in the Sequence Editor.
    """

    def get_sort_tuple(strip: bpy.types.Sequence) -> Tuple[int, int]:
        return (strip.frame_final_start, strip.frame_final_duration)

    strips = context.scene.sequence_editor.sequences_all

    if not strips:
        context.scene.frame_start = 0
        context.scene.frame_end = 0
        return (0, 0)

    strips = list(strips)
    strips.sort(key=get_sort_tuple)

    context.scene.frame_start = strips[0].frame_final_start
    context.scene.frame_end = strips[-1].frame_final_end

    return (context.scene.frame_start, context.scene.frame_end)
