import os
import structlog
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()
# Global clients
redis = None  # to be initialized in main.py
rabbit_connection = None
channel = None
httpx_client = None


# Logger configuration
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()]
    )
logger = structlog.get_logger()

print(os.getenv("RABBITMQ_URL"))


class Settings(BaseSettings):
    RABBITMQ_URL: str = os.getenv("RABBITMQ_URL")
    REDIS_URL: str = os.getenv("REDIS_URL")
    # FCM_CREDENTIALS_PATH: str = os.getenv("FCM_CREDENTIALS_JSON_PATH")
    PUSH_QUEUE_NAME: str = os.getenv("PUSH_QUEUE_NAME", "push.queue")
    REDIS_HOST: str = os.getenv("REDIS_HOST")
    REDIS_PASSWORD: str = os.getenv("REDIS_PASSWORD")
    REDIS_PORT: int = int(os.getenv("REDIS_PORT", 6379))
    API_GATEWAY_API_KEY: str = os.getenv("API_GATEWAY_API_KEY")
    API_GATEWAY_BASE_URL: str = os.getenv("API_GATEWAY_BASE_URL")



settings = Settings()

fcm_config = {
  "type": "service_account",
  "project_id": "hngpushservice",
  "private_key_id": os.getenv("FCM_PRIVATE_KEY_ID"),
  "private_key": os.getenv("FCM_PRIVATE_KEY").replace('\\n', '\n'),
  "client_email": "firebase-adminsdk-fbsvc@hngpushservice.iam.gserviceaccount.com",
  "client_id": "102838088537792723570",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
  "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/firebase-adminsdk-fbsvc%40hngpushservice.iam.gserviceaccount.com",
  "universe_domain": "googleapis.com"
}



def api_response(success: bool, data=None, error: str = None, message: str = "", meta=None):
    """Standardized API response format."""
    default_meta = {
        "total": 0, "limit": 10, "page": 1, "total_pages": 0,
        "has_next": False, "has_previous": False
    }
    return {
        "success": success,
        "data": data,
        "error": error,
        "message": message,
        "meta": meta or default_meta
    }


