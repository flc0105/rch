import platform
import sys
from dataclasses import dataclass
from enum import Enum

from core.platform.normalization import normalize_platform_alias


class PlatformAlias(str, Enum):
    WIN = 'win'
    IOS = 'ios'
    MAC = 'mac'
    LINUX = 'linux'
    UNKNOWN = 'unknown'


@dataclass(frozen=True)
class PlatformInfo:
    alias: str
    display_name: str
    system_name: str




def detect_platform_info() -> PlatformInfo:
    system_name = platform.system() or 'Unknown'

    if system_name == 'Darwin' and sys.platform == 'ios':
        return PlatformInfo(alias=PlatformAlias.IOS.value, display_name='iOS', system_name=system_name)

    alias = normalize_platform_alias(system_name, infer=True) or PlatformAlias.UNKNOWN.value
    if alias == PlatformAlias.MAC.value:
        display_name = 'macOS'
    elif alias == PlatformAlias.WIN.value:
        display_name = 'Windows'
    elif alias == PlatformAlias.LINUX.value:
        display_name = 'Linux'
    elif alias == PlatformAlias.IOS.value:
        display_name = 'iOS'
    else:
        alias = PlatformAlias.UNKNOWN.value
        display_name = system_name

    return PlatformInfo(alias=alias, display_name=display_name, system_name=system_name)


def detect_platform_alias() -> str:
    return detect_platform_info().alias


def detect_platform_name() -> str:
    return detect_platform_info().display_name
