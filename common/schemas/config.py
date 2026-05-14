from pydantic import BaseModel
from typing import Optional


class ConfigItem(BaseModel):
    key_name: str
    value: Optional[str] = None


class ConfigUpdate(BaseModel):
    value: str


class PromptUpdate(BaseModel):
    name: str
    content: str
