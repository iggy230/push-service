import asyncio
import json
import pytest
from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)

@pytest.fixture(scope="module")
async def setup():
    # Ensure Redis is clean
    await app.redis.flushall()
    yield
    await app.redis.close()

@pytest.mark.asyncio
async def test_enqueue_and_process(setup):
    payload = {
        "request_id": "ng-demo-0032",
        "user_id": "megi23",
        "device_token": {
            "token": "ff32TDFjpDqGiLxTisi-2I:APA91bFM2VB2vHS9LTR8lFgL2_p5hp1jgXPw8WyHJwPIk2isKrwwZcQm4miM2VZ5aePUz8eIR_hvAUZCam7t5TkmhfHDIpSQfy5bcQywFYxE4ksGe4rzIjs",
            "device_type": "web"
        },
        "template_data": {
            "template_id": "tmp-92039",
            "type": "push",
            "subject": "welcome to {{ server }}",
            "body": "Hello {{name}}, welcome"
        },
        "variables": {
            "name": "Ehi",
            "server": "HNG1",
            "image": "https://hng.tech/logo.png",
            "link": "https://google.com/",
            "meta": {
            "click_action": "OPEN_DASHBOARD"
            }
        }  
    }
    
    # Enqueue
    response = client.post("/enqueue", json=payload)
    assert response.status_code == 200
    assert response.json()["success"] is True

    # Wait for processing
    await asyncio.sleep(2)

    # Check status
    status_resp = client.get("/notification/test-001/status")
    assert status_resp.json()["data"]["status"] in ["delivered", "failed"]