"""Testes da API sem dispositivo: o orquestrador é substituído por um falso."""

from __future__ import annotations

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

import qagent.registry as registry_mod
from qagent.api import create_app
from qagent.config import Settings
from qagent.runlog import RunLog

KEY = {"X-API-Key": "test-key"}
STEPS = {"steps": [{"action": "tap", "locator": {"strategy": "accessibility id", "value": "View menu"}}]}


async def fake_run(ex, settings, lock):
    ex.result.status = "running"
    await asyncio.sleep(0.2)
    ex.result.status = "passed"
    for s in ex.result.steps:
        s.status = "passed"
    (ex.run_dir / "step-01.png").write_bytes(b"png")
    ex.add_artifact("step-01.png")
    ex.add_artifact("result.json")
    ex.save()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(registry_mod, "run_execution", fake_run)
    app = create_app(Settings(runs_dir=tmp_path, api_keys="test-key,other"))
    with TestClient(app) as c:
        yield c


def test_auth_required(client):
    assert client.get("/mobile/testExecution").status_code == 401
    assert client.get("/mobile/testExecution", headers={"X-API-Key": "bad"}).status_code == 401
    assert client.get("/mobile/testExecution", headers=KEY).status_code == 200


def test_no_keys_configured_returns_503(tmp_path):
    with TestClient(create_app(Settings(runs_dir=tmp_path, api_keys=""))) as c:
        assert c.get("/mobile/testExecution", headers=KEY).status_code == 503


def test_validation_is_400(client):
    r = client.post("/mobile/testExecution", json={}, headers=KEY)
    assert r.status_code == 400 and "detail" in r.json()
    r = client.post("/mobile/testExecution", json={"steps": [{"action": "tap"}]}, headers=KEY)
    assert r.status_code == 400  # tap sem locator


def test_free_text_and_gherkin_require_llm(client):
    r = client.post("/mobile/testExecution", json={"testExecution": "faz login"}, headers=KEY)
    assert r.status_code == 400 and "LLM" in r.json()["detail"]
    g = {"scenario": {"name": "x", "scenario": [{"type": "GIVEN", "description": "app aberta"}]}}
    assert client.post("/mobile/testExecution", json=g, headers=KEY).status_code == 400


def test_gherkin_becomes_ai_steps_without_normalizer_call(client):
    g = {"scenario": {"name": "Login", "scenario": [
        {"type": "GIVEN", "description": "a app está aberta"},
        {"type": "WHEN", "description": "faço login"},
        {"type": "THEN", "description": "vejo o catálogo"},
        {"type": "AND", "description": "vejo o carrinho"}]}}
    h = {**KEY, "X-Provider": "gemini", "X-LLM-API-Key": "k"}
    r = client.post("/mobile/testExecution?wait=true", json=g, headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "llm"
    assert [s["name"] for s in body["steps"]] == [
        "Given a app está aberta", "When faço login", "Then vejo o catálogo", "And vejo o carrinho"]


def test_missing_secret_is_400(client):
    body = {**STEPS, "testData": {"password": "{{secret:nao_existe}}"}}
    r = client.post("/mobile/testExecution", json=body, headers=KEY)
    assert r.status_code == 400 and "QAGENT_SECRET_NAO_EXISTE" in r.json()["detail"]


def test_create_poll_artifacts(client):
    r = client.post("/mobile/testExecution", json=STEPS, headers=KEY)
    assert r.status_code == 202
    eid = r.json()["executionId"]
    assert r.headers["X-Execution-Id"] == eid
    r = client.post("/mobile/testExecution?wait=true", json=STEPS, headers=KEY)
    assert r.status_code == 200 and r.json()["status"] == "passed"
    eid2 = r.json()["executionId"]
    assert client.get(f"/mobile/testExecution/{eid2}/artifacts/step-01.png", headers=KEY).content == b"png"
    for bad in ["..%2Fresult.json", "request.json.bak", "..\\x"]:
        assert client.get(f"/mobile/testExecution/{eid2}/artifacts/{bad}", headers=KEY).status_code == 404
    assert client.post(f"/mobile/testExecution/{eid2}/stop", headers=KEY).status_code == 409
    ids = [e["executionId"] for e in client.get("/mobile/testExecution", headers=KEY).json()]
    assert {eid, eid2} <= set(ids)


def test_secrets_never_on_disk(client, monkeypatch, tmp_path):
    monkeypatch.setenv("QAGENT_SECRET_DEMO_PASS", "s3cr3t-value")
    body = {**STEPS, "testData": {"user": "bod@example.com", "password": "{{secret:demo_pass}}",
                                  "pin": "9876"}}
    r = client.post("/mobile/testExecution?wait=true", json=body, headers=KEY)
    eid = r.json()["executionId"]
    req_json = (tmp_path / eid / "request.json").read_text(encoding="utf-8")
    assert "s3cr3t-value" not in req_json and "9876" not in req_json
    assert "{{secret:demo_pass}}" in req_json


def test_runlog_masks(tmp_path):
    log = RunLog(tmp_path / "l.jsonl", {"s3cr3t", "10203040"})
    log.write("x", args={"text": "s3cr3t"}, items=["a 10203040 b"])
    content = (tmp_path / "l.jsonl").read_text(encoding="utf-8")
    assert "s3cr3t" not in content and "10203040" not in content and "***" in content


AI_STEPS = {"steps": [{"action": "ai", "text": "Faz login com um utilizador válido"}]}


def test_ai_steps_require_llm_headers(client):
    assert client.post("/mobile/testExecution", json=AI_STEPS, headers=KEY).status_code == 400
    r = client.post("/mobile/testExecution", json=AI_STEPS, headers={**KEY, "X-Provider": "gemini"})
    assert r.status_code == 400 and "X-LLM-API-Key" in r.json()["detail"]
    r = client.post("/mobile/testExecution", json=AI_STEPS, headers={**KEY, "X-Provider": "xyz", "X-LLM-API-Key": "k"})
    assert r.status_code == 400
    r = client.post("/mobile/testExecution", json={"steps": [{"action": "ai"}]}, headers=KEY)
    assert r.status_code == 400  # ai sem text


def test_ai_execution_mode_and_key_never_on_disk(client, tmp_path):
    h = {**KEY, "X-Provider": "gemini", "X-LLM-API-Key": "AIza-super-secret-key", "X-LLM-Model": "gemini-x"}
    r = client.post("/mobile/testExecution?wait=true", json=AI_STEPS, headers=h)
    assert r.status_code == 200 and r.json()["mode"] == "llm"
    run_dir = tmp_path / r.json()["executionId"]
    for f in run_dir.iterdir():
        assert "AIza-super-secret-key" not in f.read_text(encoding="utf-8", errors="ignore"), f.name


def test_azure_requires_endpoint_deployment_and_version(client):
    h = {**KEY, "X-Provider": "azure", "X-LLM-API-Key": "k"}
    r = client.post("/mobile/testExecution", json=AI_STEPS, headers=h)
    assert r.status_code == 400
    for name in ("X-LLM-Endpoint", "X-LLM-Model", "X-LLM-APIVersion"):
        assert name in r.json()["detail"]


def test_script_is_syntax_checked_before_saving(client, monkeypatch):
    import qagent.api as api_mod
    r = client.post("/mobile/testExecution?wait=true", json=STEPS, headers=KEY)
    eid = r.json()["executionId"]
    for _ in range(50):
        if client.get(f"/mobile/testExecution/{eid}", headers=KEY).json()["status"] == "passed":
            break
        time.sleep(0.05)
    assert client.get(f"/mobile/testExecution/{eid}/script", headers=KEY).status_code == 200
    monkeypatch.setattr(api_mod, "generate_python_script", lambda *a: "def broken(:\n")
    r = client.get(f"/mobile/testExecution/{eid}/script", headers=KEY)
    assert r.status_code == 500 and "sintaxe" in r.json()["detail"]
