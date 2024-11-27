from typing import Any, Optional, Union

def input(filename: str, **kwargs: Any) -> Any: ...
def output(stream: Any, filename: str, **kwargs: Any) -> Any: ...
def trim(stream: Any, start: Optional[float] = None, end: Optional[float] = None) -> Any: ...
def run(stream: Any, overwrite_output: bool = False, **kwargs: Any) -> None: ...

class Error(Exception): 
    def __init__(self, message: str) -> None: ...
    def __str__(self) -> str: ... 