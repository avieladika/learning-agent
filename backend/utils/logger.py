from datetime import datetime
from typing import List
from pydantic import BaseModel

class LogMessage(BaseModel):
    timestamp: str
    message: str
    level: str = "INFO"

# Global list to store logs in memory
_logs: List[LogMessage] = []

def log(message: str, level: str = "INFO"):
    """
    Adds a log message to the global list and prints it.
    """
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] [{level}] {message}")
    
    _logs.append(LogMessage(
        timestamp=timestamp,
        message=message,
        level=level
    ))
    
    # Keep only last 1000 logs
    if len(_logs) > 1000:
        _logs.pop(0)

def get_logs() -> List[LogMessage]:
    return list(reversed(_logs)) # Return newest first

def clear_logs():
    _logs.clear()
