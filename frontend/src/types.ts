// Espelho do contrato da API (src/qagent/models.py; CPS 7.4 / 7.5).

export type StepStatus = "pending" | "running" | "passed" | "failed" | "skipped" | "error";
export type ExecutionStatus = "queued" | "running" | "waiting_for_user" | "passed" | "failed" | "error" | "cancelled";
export const TERMINAL: ExecutionStatus[] = ["passed", "failed", "error", "cancelled"];

export interface Locator {
  strategy: string;
  value: string;
}

export interface StructuredStep {
  name?: string;
  action: "tap" | "type" | "scroll_to" | "assert_visible" | "assert_text" | "back" | "wait" | "ai" | "manual";
  locator?: Locator;
  text?: string;
  contains?: boolean;
  timeoutSec?: number;
}

export interface GherkinStep {
  type: "GIVEN" | "WHEN" | "THEN" | "AND" | "BUT";
  description: string;
}

export interface TestExecutionInput {
  testExecution?: string;
  scenario?: { name: string; scenario: GherkinStep[] };
  steps?: StructuredStep[];
  platform: "android" | "ios";
  app?: { android?: { appPackage?: string; appActivity?: string; app?: string } };
  device: { udid?: string | null; type: "EMULATOR" | "REAL" };
  testData?: Record<string, string>;
  options: { stopOnFailure: boolean; screenshots: "every_step" | "on_failure" | "none"; resetApps?: string[];
             humanTimeoutSec?: number };
}

export interface StepResult {
  id: number;
  name: string;
  status: StepStatus;
  reason: string | null;
  actions: { tool: string; strategy: string | null; selector: string | null; result: string }[];
  locators: { strategy: string; value: string; element: string | null; fragile: boolean }[];
  evidence: { screenshot: string | null; pageSource: string | null };
  durationMs: number | null;
  tokens: Record<string, number> | null;
  outcome?: "verified" | "executed" | "inconclusive" | null;
}

export interface ExecutionResult {
  executionId: string;
  status: ExecutionStatus;
  platform: string;
  mode: "structured" | "llm";
  device: { udid: string | null; platformVersion: string | null; model?: string | null; mode: string };
  createdAt: string;
  startedAt: string | null;
  finishedAt: string | null;
  durationMs: number | null;
  summary: string;
  progress: { currentStep: number; totalSteps: number; message: string;
              awaitingUser?: string | null; awaitingSince?: string | null };
  steps: StepResult[];
  metrics: { llmCalls: number; tokensIn: number; tokensOut: number; toolCalls: number; infraRetries?: number };
  appVersions?: Record<string, string>;
  outcomes?: Record<string, number>;
  failureCategory?: "app" | "environment" | "llm" | "appium_mcp" | null;
  artifacts: string[];
}

export interface ExecutionListItem {
  executionId: string;
  status: ExecutionStatus;
  createdAt: string;
  progress: ExecutionResult["progress"];
  summary: string;
}

export interface Device {
  udid: string | null;
  platform: "android" | "ios";
  type: string;
  model?: string | null;
  remoteServerUrl?: string;
}

/** Cabeçalhos X-Provider / X-LLM-* (convenção do genai_fastapi). Só usados a partir da F2. */
export interface LlmConfig {
  provider: "none" | "azure" | "gemini";
  model: string;
  apiKey: string;
  endpoint: string;   // Azure OpenAI
  apiVersion: string; // Azure OpenAI
}
