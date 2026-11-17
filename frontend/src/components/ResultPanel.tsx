import {
  Alert, Box, Button, Chip, Divider, LinearProgress, Paper, Stack, Tooltip, Typography,
} from "@mui/material";
import DownloadIcon from "@mui/icons-material/Download";
import StopIcon from "@mui/icons-material/Stop";
import PanToolIcon from "@mui/icons-material/PanTool";
import { useState } from "react";
import { api } from "../api";
import WarningAmberIcon from "@mui/icons-material/WarningAmber";
import { downloadArtifact, fetchScript, saveText } from "../api";
import { Dialog, DialogContent, DialogTitle, DialogActions, IconButton } from "@mui/material";
import CodeIcon from "@mui/icons-material/Code";
import CloseIcon from "@mui/icons-material/Close";
import { EXEC_LABEL, STEP_LABEL, fmtMs } from "../status";
import { TERMINAL, type ExecutionResult, type StepResult } from "../types";
import { Screenshot } from "./Screenshot";

interface Props {
  result: ExecutionResult;
  stopping: boolean;
  onStop: () => void;
}

const OUTCOME_LABEL: Record<string, { label: string; title: string }> = {
  verified: { label: "verified", title: "Confirmed by a machine check on a fresh screen" },
  executed: { label: "executed", title: "Action performed; the result was not machine-checked in this step" },
  inconclusive: { label: "inconclusive", title: "Based only on the AI's reading of the screen, or the step errored" },
};

function StepRow({ step, executionId }: { step: StepResult; executionId: string }) {
  const st = STEP_LABEL[step.status];
  return (
    <Stack direction="row" spacing={2} sx={{ py: 1.5, alignItems: "flex-start" }}>
      <Typography sx={{ width: 24, pt: 0.5, color: "text.secondary", flexShrink: 0 }}>{step.id}</Typography>
      <Box sx={{ flex: 1, minWidth: 0 }}>
        <Stack direction="row" spacing={1} sx={{ alignItems: "center", flexWrap: "wrap", rowGap: 0.5 }}>
          <Chip size="small" label={st.label} color={st.color}
                variant={step.status === "skipped" || step.status === "pending" ? "outlined" : "filled"} />
          {step.outcome && (
            <Chip size="small" variant="outlined" label={OUTCOME_LABEL[step.outcome].label}
                  title={OUTCOME_LABEL[step.outcome].title}
                  color={step.outcome === "inconclusive" ? "warning" : "default"} />
          )}
          <Typography sx={{ fontWeight: 500 }}>{step.name}</Typography>
          {step.durationMs != null && (
            <Typography variant="caption" sx={{ color: "text.secondary" }}>{fmtMs(step.durationMs)}</Typography>
          )}
        </Stack>
        {step.reason && (
          <Typography variant="body2" sx={{ mt: 0.5, color: step.status === "failed" ? "error.main" : "text.secondary",
                                            overflowWrap: "anywhere" }}>
            {step.reason}
          </Typography>
        )}
        {step.locators.length > 0 && (
          <Stack direction="row" spacing={0.5} sx={{ mt: 0.75, flexWrap: "wrap", rowGap: 0.5 }}>
            {step.locators.map((l) => (
              <Tooltip key={`${l.strategy}:${l.value}`} title={l.fragile ? "xpath — fragile locator" : l.strategy}>
                <Chip size="small" variant="outlined" icon={l.fragile ? <WarningAmberIcon /> : undefined}
                      color={l.fragile ? "warning" : "default"}
                      label={`${l.strategy}: ${l.value}`}
                      sx={{ maxWidth: "100%", fontFamily: "monospace", fontSize: 11 }} />
              </Tooltip>
            ))}
          </Stack>
        )}
      </Box>
      {step.evidence.screenshot && (
        <Screenshot executionId={executionId} name={step.evidence.screenshot} title={`Step ${step.id} — ${step.name}`} />
      )}
    </Stack>
  );
}

export function ResultPanel({ result, stopping, onStop }: Props) {
  const done = TERMINAL.includes(result.status);
  const ex = EXEC_LABEL[result.status];
  const { currentStep, totalSteps, message } = result.progress;
  const finished = result.steps.filter((s) => !["pending", "running"].includes(s.status)).length;

  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Stack direction="row" spacing={1.5} sx={{ alignItems: "center", flexWrap: "wrap", rowGap: 1 }}>
        <Typography variant="h6">Execution</Typography>
        <Chip label={ex.label} color={ex.color} />
        <Typography variant="body2" sx={{ color: "text.secondary", fontFamily: "monospace" }}>
          {result.executionId}
        </Typography>
        <Box sx={{ flex: 1 }} />
        {!done && (
          <Button color="error" variant="outlined" startIcon={<StopIcon />} onClick={onStop} disabled={stopping}>
            {stopping ? "Stopping…" : "Stop"}
          </Button>
        )}
      </Stack>

      {result.status === "waiting_for_user" && result.progress.awaitingUser && (
        <AwaitingUser executionId={result.executionId} instruction={result.progress.awaitingUser}
                      since={result.progress.awaitingSince ?? null} />
      )}

      {!done && result.status !== "waiting_for_user" && (
        <Box sx={{ mt: 2 }}>
          <Typography variant="body2" sx={{ mb: 0.5 }}>
            {result.status === "running" && currentStep > 0
              ? `Executing step ${currentStep} of ${totalSteps}`
              : message}
          </Typography>
          <LinearProgress
            variant={currentStep > 0 ? "determinate" : "indeterminate"}
            value={totalSteps ? (finished / totalSteps) * 100 : 0}
          />
        </Box>
      )}

      {done && result.summary && (
        <Alert severity={result.status === "passed" ? "success" : result.status === "failed" ? "error"
                         : result.status === "cancelled" ? "info" : "warning"} sx={{ mt: 2 }}>
          {result.summary}
        </Alert>
      )}

      <Divider sx={{ my: 2 }} />
      <Box>
        {result.steps.map((s, i) => (
          <Box key={s.id}>
            {i > 0 && <Divider />}
            <StepRow step={s} executionId={result.executionId} />
          </Box>
        ))}
      </Box>

      {done && (
        <>
          <Divider sx={{ my: 2 }} />
          <Stack direction="row" spacing={3} sx={{ flexWrap: "wrap", rowGap: 1 }}>
            {result.failureCategory && (
              <Metric label="Failure category" value={{ app: "App", environment: "Environment (device/state)",
                llm: "LLM", appium_mcp: "Automation (Appium)" }[result.failureCategory]} />
            )}
            <Metric label="Duration" value={fmtMs(result.durationMs)} />
            <Metric label="Device" value={[result.device.udid, result.device.model,
              result.device.platformVersion && `Android ${result.device.platformVersion}`].filter(Boolean).join(" · ") || "—"} />
            {result.appVersions && Object.keys(result.appVersions).length > 0 && (
              <Metric label="App versions" value={Object.entries(result.appVersions)
                .map(([p, v]) => `${p} ${v}`).join(", ")} />
            )}
            {result.outcomes && Object.keys(result.outcomes).length > 0 && (
              <Metric label="Evidence" value={Object.entries(result.outcomes)
                .map(([k, n]) => `${n} ${k}`).join(" · ")} />
            )}
            {!!result.metrics.infraRetries && (
              <Metric label="Infra retries" value={String(result.metrics.infraRetries)} />
            )}
            <Metric label="Mode" value={result.mode === "llm" ? "LLM" : "Structured (no LLM)"} />
            <Metric label="Tool calls" value={String(result.metrics.toolCalls)} />
            <Metric label="LLM calls" value={String(result.metrics.llmCalls)} />
            <Metric label="Tokens in / out" value={`${result.metrics.tokensIn} / ${result.metrics.tokensOut}`} />
          </Stack>
        </>
      )}

      <Divider sx={{ my: 2 }} />
      <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap", rowGap: 1 }}>
        <GenerateCode executionId={result.executionId}
                      enabled={done && result.status !== "cancelled" && result.steps.length > 0} />
        {/* Fora de âmbito no protótipo: visíveis, mas desativados. */}
        {["Save Test", "Save Execution"].map((l) => (
          <Tooltip key={l} title="Out of scope in the prototype">
            <span><Button variant="outlined" disabled>{l}</Button></span>
          </Tooltip>
        ))}
        <Box sx={{ flex: 1 }} />
        {["result.json", "qagent.log"].map((name) => (
          <Button key={name} startIcon={<DownloadIcon />} disabled={!result.artifacts.includes(name)}
                  onClick={() => downloadArtifact(result.executionId, name)}>
            {name}
          </Button>
        ))}
      </Stack>
    </Paper>
  );
}

/** O agente pausou e pede uma ação ao QA no dispositivo (ex.: autenticação). As credenciais não passam pelo QAgent. */
function AwaitingUser({ executionId, instruction, since }: { executionId: string; instruction: string; since: string | null }) {
  const [sending, setSending] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function cont() {
    setSending(true);
    setErr(null);
    try { await api.resume(executionId); } catch (e) { setErr((e as Error).message); setSending(false); }
  }
  return (
    <Alert severity="warning" icon={<PanToolIcon />} sx={{ mt: 2, alignItems: "center" }}
           action={<Button variant="contained" color="warning" onClick={cont} disabled={sending}>
             {sending ? "Continuing…" : "Continue"}</Button>}>
      <Typography sx={{ fontWeight: 600 }}>Action needed on the device</Typography>
      <Typography variant="body2">{instruction}</Typography>
      <Typography variant="caption" sx={{ color: "text.secondary" }}>
        Do it on the device, then press Continue. Credentials you type there never go through QAgent or the LLM.
        {since ? ` Waiting since ${new Date(since).toLocaleTimeString()}.` : ""}
      </Typography>
      {err && <Typography variant="body2" color="error">{err}</Typography>}
    </Alert>
  );
}

/** Generate = descarrega o script Python + Appium; Preview = mostra-o. Gerado das ações executadas, sem LLM. */
function GenerateCode({ executionId, enabled }: { executionId: string; enabled: boolean }) {
  const [code, setCode] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function load(): Promise<string | null> {
    setBusy(true); setErr(null);
    try { const c = await fetchScript(executionId); setCode(c); return c; }
    catch (e) { setErr((e as Error).message); return null; }
    finally { setBusy(false); }
  }
  const filename = `test_${executionId}.py`;
  return (
    <>
      <Tooltip title="Python + Appium script generated from the actions that ran (no LLM). Secrets become environment variables.">
        <span>
          <Button variant="outlined" startIcon={<CodeIcon />} disabled={!enabled || busy}
                  onClick={async () => { const c = await load(); if (c) saveText(filename, c); }}>
            Generate
          </Button>
        </span>
      </Tooltip>
      <span>
        <Button variant="outlined" disabled={!enabled || busy}
                onClick={async () => { if (await load()) setOpen(true); }}>
          Preview
        </Button>
      </span>
      {err && <Typography variant="body2" color="error" sx={{ alignSelf: "center" }}>{err}</Typography>}
      <Dialog open={open} onClose={() => setOpen(false)} maxWidth="lg" fullWidth>
        <DialogTitle sx={{ pr: 6 }}>
          {filename}
          <IconButton aria-label="close" onClick={() => setOpen(false)} sx={{ position: "absolute", right: 8, top: 8 }}>
            <CloseIcon />
          </IconButton>
        </DialogTitle>
        <DialogContent dividers>
          <Box component="pre" sx={{ m: 0, fontSize: 12, fontFamily: "monospace", whiteSpace: "pre", overflowX: "auto" }}>
            {code}
          </Box>
        </DialogContent>
        <DialogActions>
          <Button startIcon={<DownloadIcon />} onClick={() => code && saveText(filename, code)}>Download</Button>
        </DialogActions>
      </Dialog>
    </>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <Box>
      <Typography variant="caption" sx={{ color: "text.secondary" }}>{label}</Typography>
      <Typography variant="body2" sx={{ fontWeight: 500 }}>{value}</Typography>
    </Box>
  );
}
