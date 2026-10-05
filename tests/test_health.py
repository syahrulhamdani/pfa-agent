"""Boundary: /health answers without needing Telegram or Gemini."""

from httpx import ASGITransport, AsyncClient

from pfa.main import app


async def test_health():
    # ASGITransport does not run the lifespan, so no bot starts.
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
