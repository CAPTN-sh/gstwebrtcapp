from dataclasses import dataclass
import enum


# TODO: add encoder parameters if needed
@dataclass
class VideoPreset:
    width: int
    height: int
    framerate: int
    bitrate: int  # kbps


class VideoPresets(enum.Enum):
    # 360p
    LD = VideoPreset(640, 360, 15, 400)
    # 480p
    SD = VideoPreset(854, 480, 20, 1000)
    # 720p
    HD = VideoPreset(1280, 720, 20, 2500)
    # 1080p
    FHD = VideoPreset(1920, 1080, 20, 4000)
    # 4K
    UHD = VideoPreset(3840, 2160, 30, 6000)


def get_video_preset(get_by: str | int) -> VideoPreset:
    if isinstance(get_by, int):
        if get_by < 0:
            return list(VideoPresets)[0].value
        elif get_by >= len(VideoPresets):
            return list(VideoPresets)[-1].value
        else:
            return list(VideoPresets)[get_by].value
    else:
        get_by = get_by.upper()
        if get_by not in VideoPresets.__members__:
            return list(VideoPresets)[0].value
        else:
            return VideoPresets[get_by].value


def get_video_preset_by_bitrate(bitrate: int | float) -> VideoPreset:
    presets = list(VideoPresets)
    if bitrate < presets[0].value.bitrate:
        return presets[0].value
    elif bitrate >= presets[-1].value.bitrate:
        return presets[-1].value
    else:
        for i, preset in enumerate(presets):
            if preset.value.bitrate <= bitrate < presets[i + 1].value.bitrate:
                return preset.value
