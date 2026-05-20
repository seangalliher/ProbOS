import pytest
from fastapi.testclient import TestClient
from src.probos.routers.work import router as work_router
from fastapi import FastAPI

app = FastAPI()
app.include_router(work_router)

@pytest.fixture
def client():
    app.state.runtime = object()
    return TestClient(app)

def test_suggested_actions_endpoint(client):
    resp = client.get('/api/work/suggested-actions')
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert any('label' in a for a in data)

def test_daily_briefing_endpoint(client):
    resp = client.get('/api/work/daily-briefing')
    assert resp.status_code == 200
    data = resp.json()
    assert 'inboxSummary' in data
    assert 'calendarSummary' in data
    assert 'suggestedActions' in data
