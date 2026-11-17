// Cliente da API do QAgent. Sem lógica de negócio: só HTTP.
import type { Device, ExecutionListItem, ExecutionResult, LlmConfig, TestExecutionInput } from "./types";

const BASE = (import.meta.env.VITE_QAGENT_API_URL as string | undefined) ?? "http://127.0.0.1:8100";
const KEY = (import.meta.env.VITE_QAGENT_API_KEY as string | undefined) ?? "";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

function detailToText(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail))
    return detail.map((d) => `${(d.loc ?? []).join(".")}: ${d.msg ?? JSON.stringify(d)}`).join("\n");
  return JSON.stringify(detail);
}

function headers(llm?: LlmConfig): HeadersInit {
  const h: Record<string, string> = { "X-API-Key": KEY };
  // A chave LLM só viaja por cabeçalho e nunca é guardada no browser.
  if (llm && llm.provider !== "none") {
    h["X-Provider"] = llm.provider;
    if (llm.model) h["X-LLM-Model"] = llm.model;
    if (llm.apiKey) h["X-LLM-API-Key"] = llm.apiKey;
    if (llm.provider === "azure") {
      if (llm.endpoint) h["X-LLM-Endpoint"] = llm.endpoint;
      if (llm.apiVersion) h["X-LLM-APIVersion"] = llm.apiVersion;
    }
  }
  return h;
}

async function request<T>(path: string, init: RequestInit = {}, llm?: LlmConfig): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, { ...init, headers: { ...headers(llm), ...(init.headers ?? {}) } });
  } catch {
    throw new ApiError(0, `API do QAgent inacessível em ${BASE}`);
  }
  if (!res.ok) {
    let msg = res.statusText;
    try {
      msg = detailToText((await res.json()).detail);
    } catch {
      /* corpo não-JSON */
    }
    throw new ApiError(res.status, msg);
  }
  return res.json() as Promise<T>;
}

export const api = {
  baseUrl: BASE,
  hasKey: KEY.length > 0,

  health: () => fetch(`${BASE}/health`).then((r) => r.json()),

  devices: () => request<{ devices: Device[] }>("/mobile/devices").then((r) => r.devices),

  create: (body: TestExecutionInput, llm: LlmConfig) =>
    request<{ executionId: string; status: string }>(
      "/mobile/testExecution",
      { method: "POST", body: JSON.stringify(body), headers: { "Content-Type": "application/json" } },
      llm,
    ),

  get: (id: string) => request<ExecutionResult>(`/mobile/testExecution/${encodeURIComponent(id)}`),

  list: () => request<ExecutionListItem[]>("/mobile/testExecution"),

  stop: (id: string) =>
    request<{ id: string; status: string }>(`/mobile/testExecution/${encodeURIComponent(id)}/stop`, {
      method: "POST",
    }),

  resume: (id: string) =>
    request<{ id: string; status: string }>(`/mobile/testExecution/${encodeURIComponent(id)}/resume`, {
      method: "POST",
    }),

  /** Artefactos exigem X-API-Key → não dá para usar <img src> direto; vai por blob. */
  artifactBlob: async (id: string, name: string): Promise<Blob> => {
    const res = await fetch(
      `${BASE}/mobile/testExecution/${encodeURIComponent(id)}/artifacts/${encodeURIComponent(name)}`,
      { headers: headers() },
    );
    if (!res.ok) throw new ApiError(res.status, `artefacto ${name}: HTTP ${res.status}`);
    return res.blob();
  },
};

/** Script Python + Appium gerado das ações executadas (GET …/script; sem LLM). */
export async function fetchScript(id: string): Promise<string> {
  const res = await fetch(`${BASE}/mobile/testExecution/${encodeURIComponent(id)}/script`, { headers: headers() });
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try { msg = detailToText((await res.json()).detail); } catch { /* corpo não-JSON */ }
    throw new ApiError(res.status, msg);
  }
  return res.text();
}

export function saveText(filename: string, text: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: "text/x-python" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export async function downloadArtifact(id: string, name: string): Promise<void> {
  const blob = await api.artifactBlob(id, name);
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${id}-${name}`;
  a.click();
  URL.revokeObjectURL(url);
}
