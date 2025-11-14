import asyncio
import json
import aio_pika
from dotenv import load_dotenv
from redis.asyncio import Redis
import structlog
import httpx
from fastapi import FastAPI, HTTPException, Request
import uvicorn
from typing import Any, Dict
from pybreaker import CircuitBreakerError, CircuitBreaker
from firebase_admin import messaging, credentials, initialize_app, auth, app_check
from jinja2 import Environment
from uuid import uuid4
from .core.config import settings, logger, api_response, fcm_config
from .core.schema import DeviceType, PushNotification, PushMessage, DeviceToken, TemplateData, TemplateResponse, UserData


load_dotenv()



app = FastAPI(title="Push Service", version="1.0.0")

# Circuit Breakers
fcm_breaker = CircuitBreaker(fail_max=5, reset_timeout=60)
template_breaker = CircuitBreaker(fail_max=3, reset_timeout=30)

# Jinja2 for template rendering
jinja_env = Environment(autoescape=True)

# Initialize Firebase
# cred = credentials.Certificate(settings.FCM_CREDENTIALS_PATH)
cred = credentials.Certificate(fcm_config)
initialize_app(cred)


@app.on_event("startup")
async def startup_event():
    app.state.redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    print("Redis connected", app.state.redis)
    asyncio.create_task(consume_push_queue())


@app.middleware("http")
async def add_correlation_id(request: Request, call_next):
    """Middleware to add X-Correlation-ID to requests and responses."""
    correlation_id = request.headers.get("X-Correlation-ID", str(uuid4()))
    structlog.contextvars.bind_contextvars(correlation_id=correlation_id)
    response = await call_next(request)
    response.headers["X-Correlation-ID"] = correlation_id
    return response


async def is_duplicate_request(request_id: str) -> bool:
    """Check if the request with given ID is a duplicate."""
    print("Checking duplicate for request_id:", request_id)
    key = f"idempotency:push:{request_id}"
    exists = await app.state.redis.set(key, "1", nx=True, ex=24*60*60)
    print("Duplicate check result:", exists)
    return exists is None


@fcm_breaker
async def send_fcm_message(device: DeviceToken, push_notification: PushNotification) -> str:
    """Send a push notification via FCM."""
    message = messaging.Message(
        token=device.token,
        notification=messaging.Notification(
            title=push_notification.title, 
            body=push_notification.body, 
            image=push_notification.image
        ),
        data={str(k): str(v) for k, v in (push_notification.data or {}).items()},
        android=messaging.AndroidConfig(
            notification=messaging.AndroidNotification(
                click_action="FLUTTER_NOTIFICATION_CLICK",
                image=push_notification.image
            )
        )if device.device_type == DeviceType.ANDROID else None,
        apns=messaging.APNSConfig(
            payload=messaging.APNSPayload(
                aps=messaging.Aps(
                    category="FLUTTER_NOTIFICATION_CLICK",
                    mutable_content=True
                )
            )
        )if device.device_type == DeviceType.IOS else None,
        webpush=messaging.WebpushConfig(
            fcm_options=messaging.WebpushFCMOptions(
                link=push_notification.link
            )
        )if device.device_type == DeviceType.WEB else None
    )
    response = messaging.send(message)
    return response


def verify_device_token(token: str) -> bool:
    """Verify Firebase device token."""
    try:
        print(token)
        decoded_token = app_check.verify_token(token)
        return True
    except Exception as e:
        logger.error("Invalid device token", error=str(e))
        return False
    

async def get_rendered_template(template_data: TemplateData, variables: Dict) -> PushNotification:
    """Fetch and render template from Template data with caching."""
    template_id = template_data['template_id']

    cache_key = f"template:rendered:{template_id}:{hash(json.dumps(variables, sort_keys=True))}"
    logger.info("Fetching template", template_id=template_id, cache_key=cache_key)
    cached = await app.state.redis.get(cache_key)
    if cached:
        logger.info("Template cache hit", template_id=template_id)
        return json.loads(cached)

    try:
        title_template = template_data['subject']
        body_template = template_data['body']

        # Render
        rendered_title = jinja_env.from_string(title_template).render(**variables)
        rendered_body = jinja_env.from_string(body_template).render(**variables)

        result = {
            'title': rendered_title,
            'body': rendered_body,
            'image': variables.get('image'),
            'link': variables.get('link'),
            'data': variables.get('data', {}) 
            }

        # Cache rendered result for 30 mins = 1800 seconds
        await app.state.redis.setex(cache_key, 1800, json.dumps(result))
        logger.info("Template rendered and cached", template_id=template_id)

        return PushNotification(**result)
    except Exception as e:
        logger.exception("Failed to fetch/render template", error=str(e))
        return PushNotification(
            title = "Notification",
            body = "Please check the app",
            image=None,
            link=None,
            data={}
            )


async def process_push_message(message: aio_pika.IncomingMessage):
    """Process incoming push notification message."""
    logger.info("Received push message", message_id=message.message_id)
    try:
        body = message.body.decode()
        payload = json.loads(body)

        notification_id = payload.get("notification_id", str(uuid4()))
        request_id = payload.get("request_id")
        if not request_id:
            logger.error("Missing request_id", payload=payload)
            await message.nack(requeue=False)
            return

        structlog.contextvars.bind_contextvars(
            notification_id=notification_id,
            request_id=request_id,
            routing_key=message.routing_key
        )

        logger.info("Processing push with template", payload=payload)

        # Idempotency
        if await is_duplicate_request(request_id):
            logger.info("Duplicate ignored", request_id=request_id)
            await message.ack()
            return

        # Extract
        user_id = payload["user_id"]
        device_token = payload["device_token"]
        template_data = payload["template_data"]
        variables = payload.get("variables", {})
        extra_data = payload.get("metadata", {})

        if not device_token or not template_data:
            logger.error("Missing required fields")
            await message.nack(requeue=False)
            return

        # if verify_device_token(device_token['token']):
        device_token = DeviceToken(
            token=device_token['token'],
            device_type = device_token.get('type', 'web')
        )
        # Fetch & render template
        rendered = await get_rendered_template(template_data, variables)
        print("Rendered template:", rendered)
        # Send FCM
        try:
            fcm_response = await send_fcm_message(
                device_token,
                rendered 
            )
            logger.info("Push delivered", fcm_response=fcm_response)
            await app.state.redis.setex(f"notification_status:{request_id}", 3600, "delivered")

        except messaging.UnregisteredError:
            logger.warning("Token unregistered", token=device_token)
            await app.state.redis.setex(f"notification_status:{request_id}", 3600, "failed:unregistered")
        except CircuitBreakerError:
            logger.error("FCM circuit open")
            await message.nack(requeue=True)
            return
        except Exception as e:
            logger.exception("FCM send failed", error=str(e))
            await message.nack(requeue=True)
            return

        await message.ack()

    except Exception as e:
        logger.exception("Message processing failed", error=str(e))
        await message.nack(requeue=False)  # To DLQ


async def consume_push_queue():
    connection = await aio_pika.connect_robust(settings.RABBITMQ_URL)
    app.state.httpx_client = httpx.AsyncClient()

    app.state.channel = await connection.channel()
    await app.state.channel.set_qos(prefetch_count=10)

    exchange = await app.state.channel.declare_exchange("notifications.direct",  durable=True)
    queue = await app.state.channel.declare_queue(settings.PUSH_QUEUE_NAME, durable=True)
    await queue.bind(exchange, routing_key=settings.PUSH_QUEUE_NAME)

    
    await queue.consume(process_push_message)
    logger.info("Push Service consuming messages", queue=settings.PUSH_QUEUE_NAME)
    await asyncio.Future()  # Keep consumer running indefinitely



@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return api_response(success=True, message="Push Service healthy")



@app.on_event("shutdown")
async def shutdown_event():
    if app.state.redis:
        await app.state.redis.close()
    if app.state.httpx_client:
        await app.state.httpx_client.aclose()
    if app.state.channel and not app.state.channel.is_closed:
        await app.state.channel.close()


@app.get("/notification/{request_id}/status")
async def get_status(request_id: str):
    """Get the status of a notification by request_id."""
    logger.info("Fetching status", request_id=request_id)
    status = await app.state.redis.get(f"notification_status:{request_id}")
    if not status:
        return api_response(success=False, error="not_found", message="Status not found")
    return api_response(success=True, data={"status": status}, message="OK")




@app.post("/enqueue")
async def enqueue_notification(payload: dict):
    """
    Test endpoint: Push raw message to push.queue
    Use in Postman to trigger Push Service without API Gateway
    """
    try:
        if not app.state.channel:
                raise HTTPException(status_code=503, detail="RabbitMQ not connected")
            
        request_id = payload.get("request_id") or f"manual-{uuid4().hex[:8]}"
        payload["request_id"] = request_id

        # Publish to RabbitMQ
        exchange = app.state.channel.default_exchange
        logger.info("Enqueuing message", exchange=exchange.name, routing_key=settings.PUSH_QUEUE_NAME)
        message = aio_pika.Message(
            body=json.dumps(payload).encode(),
            content_type="application/json",
            message_id=request_id,
            headers={"source": "enqueue_endpoint"}
        )
        await exchange.publish(
            message,
            routing_key=settings.PUSH_QUEUE_NAME
        )
        logger.info("Message enqueued successfully", request_id=request_id)
        return api_response(
            success=True,
            data={"request_id": request_id, "queue": settings.PUSH_QUEUE_NAME},
            message="Notification enqueued. Will be processed by Push Service."
        )
    except Exception as e:
        logger.exception("Failed to enqueue message", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))



@app.post("/send")
async def send_push_notification(token: DeviceToken, payload: PushNotification):
    """Send push notification directly (without queue)"""
    try:
        results = await send_fcm_message(token, payload)
        return results
    except Exception as e:
        logger.error(f"Error sending push: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8003, reload=False)