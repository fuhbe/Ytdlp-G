"""Serializable options shared by the UI, database and isolated workers."""

from dataclasses import asdict, dataclass, fields


@dataclass
class Options:
    kind: str = "video"
    container: str = "mp4"
    quality: str = "best"
    codec: str = "auto"
    bitrate: int = 192
    video_stream: str = ""
    audio_stream: str = ""
    output_mode: str = "normal"
    compression: int = 0
    organization: str = "flat"
    name_primary: str = "title"
    name_secondary: str = "id"
    name_prefix: str = ""
    subtitles: str = ""
    auto_subtitles: bool = False
    subtitle_format: str = "srt"
    embed_subtitles: bool = False
    thumbnail: bool = False
    embed_thumbnail: bool = False
    metadata: bool = True
    info_json: bool = False
    description: bool = False
    sponsor_mode: str = "off"
    sponsor_categories: str = "sponsor"
    rate_limit: int = 0
    retries: int = 3
    ffmpeg: str = ""
    ffprobe: str = ""

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            raise ValueError("invalid_options")
        obj = cls(**{k: v for k, v in data.items() if k in {f.name for f in fields(cls)}})
        for field in fields(cls):
            if type(getattr(obj, field.name)) is not field.type:
                raise ValueError("invalid_options")
        if obj.kind not in {"video", "audio", "video_only", "subtitles"}:
            raise ValueError("invalid_options")
        if obj.output_mode not in {"normal", "zip", "both"}:
            raise ValueError("invalid_options")
        if obj.container not in {
            "mp4",
            "mkv",
            "webm",
            "mov",
            "mp3",
            "m4a",
            "aac",
            "opus",
            "ogg",
            "wav",
            "flac",
            "original",
        }:
            raise ValueError("invalid_options")
        if obj.quality not in {
            "best",
            "compatible",
            "small",
            "144",
            "240",
            "360",
            "480",
            "720",
            "1080",
            "1440",
            "2160",
            "4320",
        }:
            raise ValueError("invalid_options")
        if obj.codec not in {"auto", "h264", "hevc", "av1"}:
            raise ValueError("invalid_options")
        if obj.organization not in {
            "flat",
            "channel",
            "artist",
            "album",
            "playlist",
            "date",
            "platform",
            "type",
            "resolution",
        }:
            raise ValueError("invalid_options")
        if obj.sponsor_mode not in {"off", "mark", "remove"}:
            raise ValueError("invalid_options")
        if obj.name_primary not in {
            "title",
            "id",
            "uploader",
            "artist",
            "album",
            "upload_date",
        } or obj.name_secondary not in {"id", "height", "upload_date", "none"}:
            raise ValueError("invalid_options")
        if not isinstance(obj.name_prefix, str) or len(obj.name_prefix) > 30:
            raise ValueError("invalid_options")
        allowed_categories = {
            "sponsor",
            "intro",
            "outro",
            "selfpromo",
            "preview",
            "filler",
            "interaction",
            "music_offtopic",
        }
        if not set(obj.sponsor_categories.split(",")) <= allowed_categories:
            raise ValueError("invalid_options")
        if not 0 <= int(obj.compression) <= 9 or not 0 <= int(obj.retries) <= 10:
            raise ValueError("invalid_options")
        if int(obj.bitrate) not in {64, 96, 128, 192, 256, 320} or int(obj.rate_limit) < 0:
            raise ValueError("invalid_options")
        if obj.subtitle_format not in {"srt", "vtt"}:
            raise ValueError("invalid_options")
        for stream in (obj.video_stream, obj.audio_stream):
            if stream and not all(c.isalnum() or c in "-_." for c in stream):
                raise ValueError("invalid_options")
        return obj


BUILTIN_PROFILES = {
    "best_video": Options(container="mkv"),
    "compatible_mp4": Options(quality="compatible", codec="h264"),
    "1080p": Options(quality="1080"),
    "720p": Options(quality="720"),
    "mp3_320": Options(kind="audio", container="mp3", bitrate=320),
    "original_audio": Options(kind="audio", container="original"),
    "playlist": Options(container="mkv", organization="playlist"),
    "low_data": Options(quality="small", container="mkv"),
    "zip": Options(container="mkv", output_mode="zip"),
}
