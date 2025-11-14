from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, validator
from datetime import datetime




class DeviceType(str, Enum):
    IOS = "ios"
    ANDROID = "android"
    WEB = "web"


class PushNotification(BaseModel):
    title: str = Field(..., max_length=100)
    body: str = Field(..., max_length=500)
    image: Optional[str] = None
    link: Optional[str] = None
    data: Optional[Dict[str, Any]] = {}
    
   

class DeviceToken(BaseModel):
    token: str
    device_type: DeviceType



class PushMessage(BaseModel):
    notification: PushNotification
    devices: List[DeviceToken]
    priority: str = "normal"  # normal or high
    ttl: int = 3600  # Time to live in seconds


class PushResult(BaseModel):
    success: bool
    device_token: str
    provider: str
    message: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)



class TemplateVariable(BaseModel):
    name: str
    value: Any


class TemplateRequest(BaseModel):
    template_id: str
    variables: List[TemplateVariable] = []


class TemplateResponse(BaseModel):
    title: str
    body: str




class NotificationType(str, Enum):
    PUSH = "push"
    EMAIL = "email"



class TemplateData(BaseModel):
    template_code: str
    template_id: str
    type: NotificationType
    subject: str
    body: str
    is_active: bool = True
    version: int = 1



class NotificationStatus(str, Enum):
    PENDING = "pending"
    DELIVERED = "delivered"
    FAILED = "failed"


class UserData(BaseModel):
    name: str
    link: Optional[str] = None
    image: Optional[str] = None
    push_token: DeviceToken
    meta: Optional[Dict[str, Any]] = {}


class NotificationRecord(BaseModel):
    notification_type: NotificationType
    user_id: str
    template_code: str
    variables: Dict[str, Any]
    request_id: str
    priority: int = 5
    metadata: Optional[Dict[str, Any]] = {}


class NoticationStatus(str, Enum):
    delivered = "delivered"
    pending = "pending"
    failed = "failed"
