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
# (c) 2021, Blender Foundation

import logging
import sys
from typing import List, Optional, Dict, Tuple


class LoggerFactory:

    """
    Utility class to streamline logger creation
    """

    @staticmethod
    def getLogger(name=__name__):
        name = name
        """
        formatter = logging.Formatter("%(levelname)s:%(name)s: %(message)s")
        consoleHandler = logging.StreamHandler(sys.stdout)
        consoleHandler.setFormatter(formatter)
        """
        logger = logging.getLogger(name)
        """
        logger.addHandler(consoleHandler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
        """
        return logger


logger = LoggerFactory.getLogger(__name__)


class LoggerLevelManager:
    logger_levels: List[Tuple[logging.Logger, int]] = []

    @classmethod
    def configure_levels(cls):
        cls.logger_levels = []
        for key in logging.Logger.manager.loggerDict:
            if key.startswith("urllib3"):
                # save logger and value
                logger = logging.getLogger(key)
                cls.logger_levels.append((logger, logger.level))

                logger.setLevel(logging.CRITICAL)
        logger.info("Configured logging Levels.")

    @classmethod
    def restore_levels(cls):
        for logger, level in cls.logger_levels:
            logger.setLevel(level)
        logger.info("Restored logging Levels.")


def gen_processing_string(item: str) -> str:
    return f"---Processing {item}".ljust(50, "-")


def log_new_lines(multiplier: int) -> None:
    print("\n" * multiplier)