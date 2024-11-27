from typing import Any, Optional, Dict, Union
from flask import Flask

class CORS:
    def __init__(
        self,
        app: Optional[Flask] = None,
        resources: Optional[Dict[str, Dict[str, Any]]] = None,
        **kwargs: Any
    ) -> None: ...

def cross_origin(*args: Any, **kwargs: Any) -> Any: ... 