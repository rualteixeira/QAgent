import type { ExecutionStatus, StepStatus } from "./types";

type Color = "default" | "primary" | "secondary" | "error" | "info" | "success" | "warning";

// Rótulos dos estados na interface (os de falha/não executado ainda podem mudar).
export const STEP_LABEL: Record<StepStatus, { label: string; color: Color }> = {
  pending: { label: "Waiting", color: "default" },
  running: { label: "Running", color: "info" },
  passed: { label: "Executed", color: "success" },
  failed: { label: "Failed", color: "error" },
  skipped: { label: "Skipped", color: "default" },
  error: { label: "Error", color: "warning" },
};

export const EXEC_LABEL: Record<ExecutionStatus, { label: string; color: Color }> = {
  queued: { label: "Queued", color: "default" },
  running: { label: "Running", color: "info" },
  waiting_for_user: { label: "Waiting for you", color: "warning" },
  passed: { label: "Passed", color: "success" },
  failed: { label: "Failed", color: "error" },
  error: { label: "Error", color: "warning" },
  cancelled: { label: "Cancelled", color: "default" },
};

export function fmtMs(ms: number | null | undefined): string {
  if (ms == null) return "—";
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}
