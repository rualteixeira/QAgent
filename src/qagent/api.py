"""API FastAPI do QAgent. Arranque: uv run uvicorn qagent.api:app --port 8100"""

from __future__ import annotations

import asyncio
import logging
import secrets
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from qagent.codegen import generate_python_script, load_request
from qagent.config import Settings, get_settings
from qagent.health import HealthChecker, adb_devices
from qagent.llm import LlmConfigError, params_from_headers
from qagent.models import (TERMINAL, ExecutionCreated, ExecutionListItem, ExecutionResult,
                           TestExecutionInput)
from qagent.orchestrator import SecretError
from qagent.registry import Registry, artifact_path

# O endpoint /sse do appium-mcp envia um evento legado "endpoint" que o cliente mcp regista
# como aviso em cada ligação. É só ruído.
logging.getLogger("mcp.client.streamable_http").setLevel(logging.ERROR)
log = logging.getLogger("qagent")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    registry = Registry(settings)
    health = HealthChecker(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.runs_dir.mkdir(parents=True, exist_ok=True)
        pruned = registry.prune_old_runs()
        if pruned:
            log.info("QAgent: %d execuções com mais de %d dias apagadas", len(pruned), settings.runs_retention_days)
        n = registry.load_from_disk()
        log.info("QAgent: %d execuções carregadas de %s", n, settings.runs_dir)
        if not settings.api_key_set:
            log.warning("QAGENT_API_KEYS vazio: as rotas protegidas vão responder 503")
        yield
        await registry.shutdown()

    app = FastAPI(title="QAgent", version="0.1.0", lifespan=lifespan)
    app.state.registry = registry
    app.state.settings = settings
    app.add_middleware(
        CORSMiddleware, allow_origins=settings.cors_origin_list, allow_methods=["GET", "POST"],
        allow_headers=["*"], expose_headers=["X-Execution-Id"])

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        # Erros de validação respondem 400 (em vez do 422 do FastAPI) com {"detail": ...}
        errors = [{"loc": e["loc"], "msg": e["msg"]} for e in exc.errors()]
        return JSONResponse(status_code=400, content={"detail": errors})

    def require_key(x_api_key: str | None = Header(None)) -> None:
        keys = settings.api_key_set
        if not keys:
            raise HTTPException(503, "QAGENT_API_KEYS não configurado no servidor")
        if not x_api_key or not any(secrets.compare_digest(x_api_key, k) for k in keys):
            raise HTTPException(401, "X-API-Key inválida ou em falta")

    auth = [Depends(require_key)]

    def get_ex(eid: str):
        ex = registry.get(eid)
        if not ex:
            raise HTTPException(404, f"execução '{eid}' não encontrada")
        return ex

    @app.get("/health")
    async def get_health(response: Response):
        data = await health.get()
        if data["status"] != "ok":
            response.status_code = 503
        return data

    @app.get("/mobile/devices", dependencies=auth)
    async def get_devices():
        devices = [d for d in await adb_devices() if d["state"] == "device"]
        if settings.ios_remote_server_url:
            devices.append({"udid": None, "platform": "ios", "type": "REMOTE",
                            "remoteServerUrl": settings.ios_remote_server_url})
        return {"devices": devices}

    @app.post("/mobile/testExecution", dependencies=auth, status_code=202,
              response_model=ExecutionCreated | ExecutionResult, response_model_by_alias=True)
    async def post_execution(body: TestExecutionInput, response: Response,
                             wait: bool = Query(False, description="Modo síncrono: espera pelo fim da execução"),
                             wait_timeout_sec: float = Query(600, alias="waitTimeoutSec", gt=0, le=3600),
                             x_provider: str | None = Header(None),
                             x_llm_model: str | None = Header(None, alias="X-LLM-Model"),
                             x_llm_api_key: str | None = Header(None, alias="X-LLM-API-Key"),
                             x_llm_endpoint: str | None = Header(None, alias="X-LLM-Endpoint"),
                             x_llm_api_version: str | None = Header(None, alias="X-LLM-APIVersion")):
        try:
            llm_params = params_from_headers(x_provider, x_llm_model, x_llm_api_key, x_llm_endpoint,
                                             x_llm_api_version)
        except LlmConfigError as e:
            raise HTTPException(400, str(e)) from e
        needs_llm = not body.steps or any(s.action == "ai" for s in body.steps)
        if needs_llm and not llm_params:
            raise HTTPException(400, "texto livre, Gherkin e passos 'ai' exigem um LLM: "
                                     "cabeçalhos X-Provider e X-LLM-*")
        if body.platform != "android" or body.device.remote_server_url:
            raise HTTPException(501, "Por agora só é suportado Android local.")
        try:
            ex = registry.create(body, llm_params)
        except SecretError as e:
            raise HTTPException(400, str(e)) from e
        response.headers["X-Execution-Id"] = ex.id
        if wait:
            try:
                await asyncio.wait_for(asyncio.shield(ex.task), wait_timeout_sec)
            except asyncio.TimeoutError:
                pass
            if ex.result.status in TERMINAL:
                response.status_code = 200
                return ex.result
        return ExecutionCreated(execution_id=ex.id, status=ex.result.status)

    @app.get("/mobile/testExecution", dependencies=auth, response_model=list[ExecutionListItem],
             response_model_by_alias=True)
    async def list_executions():
        return [ExecutionListItem(execution_id=e.id, status=e.result.status, created_at=e.result.created_at,
                                  progress=e.result.progress, summary=e.result.summary)
                for e in registry.list()]

    @app.get("/mobile/testExecution/{eid}", dependencies=auth, response_model=ExecutionResult,
             response_model_by_alias=True)
    async def get_execution(eid: str):
        return get_ex(eid).result

    @app.post("/mobile/testExecution/{eid}/stop", dependencies=auth)
    async def stop_execution(eid: str):
        ex = get_ex(eid)
        if ex.result.status in TERMINAL:
            raise HTTPException(409, f"execução já terminou com estado '{ex.result.status}'")
        registry.stop(eid)
        return {"id": eid, "status": "stopping"}

    @app.post("/mobile/testExecution/{eid}/resume", dependencies=auth)
    async def resume_execution(eid: str):
        """O QA concluiu a ação pedida no dispositivo (ex.: autenticação) → a execução continua."""
        ex = get_ex(eid)
        if not registry.resume(eid):
            raise HTTPException(409, f"a execução não está à espera do utilizador (estado '{ex.result.status}')")
        return {"id": eid, "status": "resuming"}

    @app.get("/mobile/testExecution/{eid}/script", dependencies=auth)
    async def get_script(eid: str):
        """Script Python + Appium gerado das ações executadas (sem LLM)."""
        ex = get_ex(eid)
        if ex.result.status not in TERMINAL:
            raise HTTPException(409, f"a execução ainda não terminou (estado '{ex.result.status}')")
        if ex.result.status == "cancelled" or not ex.result.steps:
            raise HTTPException(409, "execução cancelada ou sem passos: não há nada para gerar")
        try:
            code = generate_python_script(ex.result, load_request(ex.run_dir))
        except FileNotFoundError as e:
            raise HTTPException(404, "request.json da execução não encontrado") from e
        if any(s and len(s) >= 3 and s in code for s in ex.secrets):
            raise HTTPException(500, "o script gerado conteria um segredo; geração recusada")
        try:  # validar a sintaxe antes de gravar/entregar
            compile(code, f"test_{eid}.py", "exec")
        except SyntaxError as e:
            raise HTTPException(500, f"o script gerado tem um erro de sintaxe (linha {e.lineno}); não foi gravado") from e
        name = f"test_{eid}.py"
        (ex.run_dir / name).write_text(code, encoding="utf-8")
        ex.add_artifact(name)
        ex.save()
        return FileResponse(ex.run_dir / name, media_type="text/x-python", filename=name)

    @app.get("/mobile/testExecution/{eid}/artifacts/{name}", dependencies=auth)
    async def get_artifact(eid: str, name: str):
        path = artifact_path(get_ex(eid), name)
        if not path:
            raise HTTPException(404, f"artefacto '{name}' não encontrado")
        return FileResponse(path)

    return app


app = create_app()
