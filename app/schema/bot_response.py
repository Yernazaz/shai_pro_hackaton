from typing import Any, Dict, List, Optional
from pydantic import BaseModel

class BotResponse(BaseModel):
    sql_query: Optional[str]
    type: str
    status: str
    appointments: List[Dict[str, Any]]
    human_readable_text: str

    class Config:
        extra = "allow" 
