"""Humano no circuito: pausa (waiting_for_user) → POST resume → continua. Sem dispositivo."""

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

import qagent.registry as registry_mod
from qagent.api import create_app
from qagent.config import Settings
from qagent.orchestrator import _wait_for_human

KEY = {"X-API-Key": "k"}
BODY = {"steps": [{"action": "manual", "text": "Faz login na app no dispositivo"}],
        "options": {"humanTimeoutSec": 30}}


async def fake_run(ex, settings, lock):
    ex.result.status = "running"
    ex.save()
    await _wait_for_human(ex, 1, ex.steps[0].text)
    ex.result.status = "passed"
    ex.save()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(registry_mod, "run_execution", fake_run)
    with TestClient(create_app(Settings(runs_dir=tmp_path, api_keys="k"))) as c:
        yield c


def _status(c, eid):
    return c.get(f"/mobile/testExecution/{eid}", headers=KEY).json()


def test_pause_and_resume(client):
    eid = client.post("/mobile/testExecution", json=BODY, headers=KEY).json()["executionId"]
    for _ in range(50):
        r = _status(client, eid)
        if r["status"] == "waiting_for_user":
            break
        time.sleep(0.05)
    assert r["status"] == "waiting_for_user"
    assert r["progress"]["awaitingUser"] == "Faz login na app no dispositivo"
    assert client.post(f"/mobile/testExecution/{eid}/resume", headers=KEY).status_code == 200
    for _ in range(50):
        r = _status(client, eid)
        if r["status"] == "passed":
            break
        time.sleep(0.05)
    assert r["status"] == "passed" and r["progress"]["awaitingUser"] is None
    # já não está à espera → 409
    assert client.post(f"/mobile/testExecution/{eid}/resume", headers=KEY).status_code == 409


def test_manual_step_needs_no_llm(client):
    assert client.post("/mobile/testExecution", json=BODY, headers=KEY).status_code == 202
