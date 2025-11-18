from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

class BaseDataReader(ABC):
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._validate_config()
        self._client = None
    
    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = self._connect()
        return self._client
    
    @abstractmethod
    def _validate_config(self) -> None:
        pass
    
    @abstractmethod
    def _connect(self) -> Any:
        pass
    
    @abstractmethod
    def query(self, input: Any, **kwargs) -> Any:
        pass
    
    def close(self) -> None:
        if self._client is not None:
            self._client.close()