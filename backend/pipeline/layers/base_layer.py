from abc import ABC, abstractmethod
from typing import Any

class BaseLayer(ABC):
    """
    Abstract base class for a pipeline layer.
    Each layer must implement the execute method.
    """
    
    @abstractmethod
    def execute(self, *args, **kwargs) -> Any:
        """
        Executes the logic of the layer.
        
        Returns:
            Any: The output of the layer, to be passed to the next layer.
        """
        pass
