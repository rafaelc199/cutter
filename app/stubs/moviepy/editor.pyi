from typing import Optional, Any

class VideoFileClip:
    duration: float
    
    def __init__(self, filename: str) -> None: ...
    def subclip(self, start_time: float, end_time: float) -> 'VideoFileClip': ...
    def write_videofile(
        self,
        filename: str,
        codec: str = ...,
        audio_codec: str = ...,
        temp_audiofile: str = ...,
        remove_temp: bool = ...,
        threads: int = ...,
        preset: str = ...,
        logger: Any = ...
    ) -> None: ...
    def close(self) -> None: ... 