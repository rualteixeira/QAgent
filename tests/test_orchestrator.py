"""G1 — orquestrador + grafo com appium-mcp simulado: limpeza da sessão, stopOnFailure, verificação do
dispositivo e classificação das falhas (CA5)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import qagent.orchestrator as orch
from qagent.config import Settings
from qagent.mcp_client import ToolError
from qagent.models import TestExecutionInput
from qagent.registry import Registry

XML = (Path(__file__).parent / "data" / "login_error_screen.xml").read_text(encoding="utf-8")
LOGIN_BTN = {"strategy": "accessibility id", "value": "Tap to login with given credentials"}
ERR_ID = {"strategy": "id", "value": "com.saucelabs.mydemoapp.android:id/passwordErrorTV"}


class _Res:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeMcp:
    instances: list["FakeMcp"] = []

    create_failures_left = 0  # G3: falhar a criação da sessão N vezes (entre ligações) e depois funcionar

    def __init__(self, *a, create_error: str | None = None, **kw) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.connect_ms, self.mcp_session_id = 1, "mcp-1"
        self.create_error = create_error
        FakeMcp.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    def did(self, name: str, **match) -> bool:
        return any(n == name and all(a.get(k) == v for k, v in match.items()) for n, a in self.calls)

    async def call(self, name, args=None, *, timeout_s=None):
        args = dict(args or {})
        self.calls.append((name, args))
        if name == "select_device":
            return _Res('{"capabilities": {"appium:udid": "emulator-5554"}}')
        if name == "appium_session_management" and args.get("action") == "create":
            if self.create_error and FakeMcp.create_failures_left != 0:
                FakeMcp.create_failures_left -= 1
                raise ToolError(self.create_error)
            return _Res("ANDROID session created successfully with ID: 12345678-aaaa-bbbb-cccc-1234567890ab")
        if name == "appium_session_management":
            return _Res("No active sessions found." if args.get("action") == "list" else "ok")
        if name == "appium_get_page_source":
            return _Res(f"Page source retrieved successfully: \n```xml {XML}```")
        if name == "appium_find_element":
            return _Res("elementId 'el-1'")
        if name == "appium_get_text":
            return _Res("Successfully got text Sorry this user has been locked out. from element el-1")
        if name == "appium_screenshot":
            return _Res("Screenshot saved successfully to: C:\\nao\\existe.png")
        return _Res("ok")


def _setup(monkeypatch, tmp_path, precheck: str | None = None, create_error: str | None = None,
           create_failures: int = -1):
    FakeMcp.instances.clear()
    FakeMcp.create_failures_left = create_failures  # -1 = falha sempre
    monkeypatch.setattr(orch, "McpConnection", lambda *a, **kw: FakeMcp(create_error=create_error))

    async def fake_precheck(udid):
        return precheck

    async def fake_first():
        return "emulator-5554"

    async def fake_props(udid):
        return {"platformVersion": "16", "model": "sdk_gphone64"}

    async def fake_versions(udid, pkgs):
        return {p: "1.2.3" for p in pkgs}
    monkeypatch.setattr(orch, "device_precheck", fake_precheck)
    monkeypatch.setattr(orch, "first_ready_device", fake_first)
    monkeypatch.setattr(orch, "device_props", fake_props)
    monkeypatch.setattr(orch, "app_versions", fake_versions)

    async def fake_home(udid):
        return "com.vendor.home"
    monkeypatch.setattr(orch, "home_package", fake_home)
    monkeypatch.setattr(orch, "RETRY_DELAY_S", 0)
    return Registry(Settings(runs_dir=tmp_path, api_keys="k"))



def _run(registry: Registry, body: dict, cancel_after: float | None = None):
    async def go():
        ex = registry.create(TestExecutionInput.model_validate(body))
        if cancel_after is not None:
            await asyncio.sleep(cancel_after)
            registry.stop(ex.id)
        await asyncio.gather(ex.task, return_exceptions=True)
        return ex
    return asyncio.run(go())


def test_functional_failure_stops_skips_rest_and_cleans_up(monkeypatch, tmp_path):
    reg = _setup(monkeypatch, tmp_path)
    ex = _run(reg, {"steps": [
        {"action": "tap", "locator": LOGIN_BTN},
        {"action": "assert_text", "locator": ERR_ID, "text": "Products", "timeoutSec": 0.5},
        {"action": "tap", "locator": LOGIN_BTN}]})
    r = ex.result
    assert [s.status for s in r.steps] == ["passed", "failed", "skipped"]
    assert r.status == "failed" and r.failure_category == "app" and r.steps[1].failure_category == "app"
    assert "locked out" in r.steps[1].reason                      # o texto observado vai no motivo
    assert FakeMcp.instances[0].did("appium_session_management", action="delete")
    assert [s.outcome for s in r.steps] == ["executed", "verified", None]   # G3
    assert r.outcomes == {"executed": 1, "verified": 1} and r.metrics.infra_retries == 0
    assert (r.device.platform_version, r.device.model) == ("16", "sdk_gphone64")


def test_unresponsive_device_fails_fast_as_environment(monkeypatch, tmp_path):
    reg = _setup(monkeypatch, tmp_path, precheck="O dispositivo emulator-5554 não responde (adb sem resposta em 10s)")
    ex = _run(reg, {"steps": [{"action": "tap", "locator": LOGIN_BTN}]})
    r = ex.result
    assert r.status == "error" and r.failure_category == "environment"
    assert r.summary.startswith("Ambiente:") or "não responde" in r.summary
    assert not FakeMcp.instances                                    # nem chegou a abrir a ligação MCP
    assert all(s.status == "skipped" for s in r.steps)


def test_session_creation_adb_timeout_is_environment(monkeypatch, tmp_path):
    reg = _setup(monkeypatch, tmp_path, create_error="appium_session_management: Failed to create session. "
                 "Error executing adbExec ... timed out after 20000ms")
    ex = _run(reg, {"steps": [{"action": "tap", "locator": LOGIN_BTN}]})
    assert ex.result.status == "error" and ex.result.failure_category == "environment"
    assert ex.result.metrics.infra_retries == 1 and len(FakeMcp.instances) == 2   # 1 nova tentativa (omissão)


def test_session_creation_is_retried_and_then_runs(monkeypatch, tmp_path):
    reg = _setup(monkeypatch, tmp_path, create_error="Failed to create session. adb timed out", create_failures=1)
    ex = _run(reg, {"steps": [{"action": "tap", "locator": LOGIN_BTN}],
                    "app": {"android": {"appPackage": "com.example.app"}}})
    r = ex.result
    assert r.status == "passed" and r.metrics.infra_retries == 1
    assert r.app_versions == {"com.example.app": "1.2.3"}


def test_no_retry_when_disabled(monkeypatch, tmp_path):
    reg = _setup(monkeypatch, tmp_path, create_error="adb timed out", create_failures=1)
    ex = _run(reg, {"steps": [{"action": "tap", "locator": LOGIN_BTN}], "options": {"infraRetries": 0}})
    assert ex.result.status == "error" and ex.result.metrics.infra_retries == 0


def test_locks_are_per_device(tmp_path):
    reg = Registry(Settings(runs_dir=tmp_path, api_keys="k"))
    assert reg.lock_for("emulator-5554") is reg.lock_for("emulator-5554")
    assert reg.lock_for("emulator-5554") is not reg.lock_for("emulator-5556")


def test_step_outcome_rules():
    from qagent.models import ActionRecord as A, StepResult as SR, StructuredStep as St
    ai = St(action="ai", text="x")
    def sr(status, *acts):
        return SR(id=1, name="x", status=status, actions=list(acts))
    assert orch.step_outcome(ai, sr("passed", A(tool="tap", result="ok"))) == "executed"
    assert orch.step_outcome(ai, sr("passed", A(tool="tap", result="ok"), A(tool="assert", result="ok"))) == "verified"
    assert orch.step_outcome(ai, sr("failed", A(tool="assert", result="not_met"))) == "verified"
    assert orch.step_outcome(ai, sr("failed", A(tool="wait_for_text", result="timeout 10s"))) == "verified"
    assert orch.step_outcome(ai, sr("failed", A(tool="assert", result="expected"))) == "inconclusive"
    assert orch.step_outcome(ai, sr("passed", A(tool="look_at_screen", result="ok"))) == "inconclusive"
    assert orch.step_outcome(ai, sr("error")) == "inconclusive"
    assert orch.step_outcome(ai, sr("skipped")) is None
    assert orch.step_outcome(St(action="manual", text="x"), sr("passed")) == "executed"


def test_stop_cancels_and_still_deletes_the_session(monkeypatch, tmp_path):
    reg = _setup(monkeypatch, tmp_path)
    ex = _run(reg, {"steps": [{"action": "wait", "timeoutSec": 30}, {"action": "tap", "locator": LOGIN_BTN}]},
              cancel_after=0.5)
    r = ex.result
    assert r.status == "cancelled"
    assert [s.status for s in r.steps] == ["skipped", "skipped"]
    assert FakeMcp.instances[0].did("appium_session_management", action="delete")


def test_classify_exception():
    assert orch.classify_exception(ToolError("adb ... timed out")) == "environment"
    assert orch.classify_exception(ToolError("appium_find_element: invalid selector")) == "appium_mcp"
    assert orch.classify_exception(orch.NormalizerError("x")) == "llm"
    assert orch.classify_exception(orch.HumanTimeout("x")) == "environment"


def test_retention_prunes_only_old_finished_runs(tmp_path):
    import json as _json
    from datetime import datetime, timezone
    def mk(name, status, finished):
        d = tmp_path / name
        d.mkdir()
        (d / "result.json").write_text(_json.dumps({"status": status, "finishedAt": finished}), encoding="utf-8")
    mk("aaaaaaaaaaaa", "passed", "2026-01-01T00:00:00Z")      # antiga, terminada → apagada
    mk("bbbbbbbbbbbb", "passed", "2026-11-12T00:00:00Z")      # recente → mantida
    mk("cccccccccccc", "running", "2026-01-01T00:00:00Z")     # não terminada → mantida
    mk("f5", "passed", "2026-01-01T00:00:00Z")                # pasta de fase → nunca
    now = datetime(2026, 11, 13, tzinfo=timezone.utc)
    assert Registry(Settings(runs_dir=tmp_path, api_keys="k")).prune_old_runs(now) == []   # omissão: desligado
    reg = Registry(Settings(runs_dir=tmp_path, api_keys="k", runs_retention_days=30))
    assert reg.prune_old_runs(now) == ["aaaaaaaaaaaa"]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["bbbbbbbbbbbb", "cccccccccccc", "f5"]


def test_reset_of_app_under_test_relaunches_it(monkeypatch, tmp_path):
    reg = _setup(monkeypatch, tmp_path)
    ex = _run(reg, {"steps": [{"action": "tap", "locator": LOGIN_BTN}],
                    "app": {"android": {"appPackage": "com.example.app"}},
                    "options": {"resetApps": ["com.example.app", "com.example.other"]}})
    mcp = FakeMcp.instances[0]
    assert mcp.did("appium_app_lifecycle", action="clear", id="com.example.other")
    assert mcp.did("appium_app_lifecycle", action="activate", id="com.example.app")
    assert not mcp.did("appium_app_lifecycle", action="activate", id="com.example.other")
    assert ex.result.status == "passed"
