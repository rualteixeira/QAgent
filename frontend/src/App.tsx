import { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert, AppBar, Box, Button, Chip, Container, FormControl, FormControlLabel, InputLabel, MenuItem,
  Paper, Select, Snackbar, Stack, Switch, Tab, Tabs, TextField, Toolbar, Tooltip, Typography,
} from "@mui/material";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import RefreshIcon from "@mui/icons-material/Refresh";
import SaveIcon from "@mui/icons-material/Save";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutlined";
import { ApiError, api } from "./api";
import { ResultPanel } from "./components/ResultPanel";
import { EXEC_LABEL } from "./status";
import {
  TERMINAL, type Device, type ExecutionListItem, type ExecutionResult, type GherkinStep, type LlmConfig,
  type TestExecutionInput,
} from "./types";

type InputMode = "manual" | "gherkin" | "structured";
const POLL_MS = 1500;


/** Uma linha "Given/When/Then/And/But …" por passo → scenario Gherkin do pedido. */
function parseGherkin(text: string): TestExecutionInput["scenario"] {
  let name = "Scenario";
  const steps: GherkinStep[] = [];
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    const sc = line.match(/^(?:Scenario|Cenário)\s*:\s*(.+)$/i);
    if (sc) { name = sc[1]; continue; }
    const m = line.match(/^(Given|When|Then|And|But|Dado|Quando|Então|E|Mas)\s+(.+)$/i);
    if (!m) continue;
    const map: Record<string, GherkinStep["type"]> = {
      given: "GIVEN", dado: "GIVEN", when: "WHEN", quando: "WHEN", then: "THEN", "então": "THEN",
      and: "AND", e: "AND", but: "BUT", mas: "BUT",
    };
    steps.push({ type: map[m[1].toLowerCase()], description: m[2] });
  }
  return { name, scenario: steps };
}

// Configuração do GenAI Server guardada pelo próprio utilizador (botão "Save").
// A chave nunca é guardada. localStorage pode falhar (modo privado, bloqueio) → try/catch.
const SETTINGS_KEY = "qagent.genaiServer";
const EMPTY_LLM: LlmConfig = { provider: "none", model: "", apiKey: "", endpoint: "", apiVersion: "" };

function loadSavedLlm(): LlmConfig {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (!raw) return EMPTY_LLM;
    const s = JSON.parse(raw) as Partial<LlmConfig>;
    return { ...EMPTY_LLM, provider: s.provider ?? "none", model: s.model ?? "",
             endpoint: s.endpoint ?? "", apiVersion: s.apiVersion ?? "" };
  } catch {
    return EMPTY_LLM;
  }
}

export default function App() {
  // GenAI Server (cabeçalhos X-Provider/X-LLM-*).
  const [llm, setLlm] = useState<LlmConfig>(loadSavedLlm);
  const [savedMsg, setSavedMsg] = useState<string | null>(null);

  // Os valores do GenAI Server são sempre introduzidos pelo utilizador (nada pré-preenchido).
  function selectProvider(provider: LlmConfig["provider"]) {
    setLlm({ ...EMPTY_LLM, provider });
  }

  function saveLlmSettings() {
    try {
      const { provider, model, endpoint, apiVersion } = llm;  // sem apiKey
      localStorage.setItem(SETTINGS_KEY, JSON.stringify({ provider, model, endpoint, apiVersion }));
      setSavedMsg("Settings saved in this browser (the API key is not saved).");
    } catch {
      setSavedMsg("Could not save: browser storage is not available.");
    }
  }

  function clearLlmSettings() {
    try { localStorage.removeItem(SETTINGS_KEY); } catch { /* ignorar */ }
    setLlm(EMPTY_LLM);
    setSavedMsg("Saved settings removed.");
  }

  const [devices, setDevices] = useState<Device[]>([]);
  const [deviceUdid, setDeviceUdid] = useState("");
  const [appPackage, setAppPackage] = useState("");
  const [appActivity, setAppActivity] = useState("");
  const [appPath, setAppPath] = useState("");
  const [stopOnFailure, setStopOnFailure] = useState(true);
  const [screenshots, setScreenshots] = useState<TestExecutionInput["options"]["screenshots"]>("every_step");
  const [resetApps, setResetApps] = useState("");

  // Sem textos de exemplo: o ecrã não assume nenhuma app (só placeholders genéricos).
  const [mode, setMode] = useState<InputMode>("manual");
  const [manualText, setManualText] = useState("");
  const [gherkinText, setGherkinText] = useState("");
  // Test data dos separadores texto livre / Gherkin (JSON). Vazio por omissão: valores do utilizador.
  const [testDataText, setTestDataText] = useState("");
  const [structuredText, setStructuredText] = useState("");

  const [result, setResult] = useState<ExecutionResult | null>(null);
  const [history, setHistory] = useState<ExecutionListItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [stopping, setStopping] = useState(false);
  const pollRef = useRef<number | null>(null);

  const loadDevices = useCallback(() => {
    api.devices()
      .then((d) => {
        setDevices(d);
        setDeviceUdid((cur) => cur || d.find((x) => x.platform === "android")?.udid || "");
      })
      .catch((e: ApiError) => setError(`Devices: ${e.message}`));
  }, []);
  const loadHistory = useCallback(() => { api.list().then(setHistory).catch(() => {}); }, []);

  useEffect(() => { loadDevices(); loadHistory(); }, [loadDevices, loadHistory]);

  // Polling do estado.
  const stopPolling = () => { if (pollRef.current) window.clearInterval(pollRef.current); pollRef.current = null; };
  const startPolling = useCallback((id: string) => {
    stopPolling();
    const tick = async () => {
      try {
        const r = await api.get(id);
        setResult(r);
        if (TERMINAL.includes(r.status)) { stopPolling(); setStopping(false); loadHistory(); }
      } catch (e) {
        setError((e as Error).message);
        stopPolling();
      }
    };
    tick();
    pollRef.current = window.setInterval(tick, POLL_MS);
  }, [loadHistory]);
  useEffect(() => stopPolling, []);

  function buildBody(): TestExecutionInput {
    const android: NonNullable<NonNullable<TestExecutionInput["app"]>["android"]> = {};
    if (appPackage) android.appPackage = appPackage;
    if (appActivity) android.appActivity = appActivity;
    if (appPath) android.app = appPath;
    const base: TestExecutionInput = {
      platform: "android",
      device: { udid: deviceUdid || null, type: deviceUdid.startsWith("emulator-") ? "EMULATOR" : "REAL" },
      options: { stopOnFailure, screenshots,
                 resetApps: resetApps.split(/[\s,]+/).map((p) => p.trim()).filter(Boolean) },
      ...(Object.keys(android).length ? { app: { android } } : {}),
    };
    if (mode === "manual" || mode === "gherkin") {
      let testData: Record<string, string> = {};
      if (testDataText.trim()) {
        try { testData = JSON.parse(testDataText); } catch (e) {
          throw new Error(`Invalid test data JSON: ${(e as Error).message}`);
        }
      }
      if (mode === "manual") return { ...base, testExecution: manualText, testData };
      const scenario = parseGherkin(gherkinText);
      if (!scenario?.scenario.length) throw new Error("No Given/When/Then lines found.");
      return { ...base, scenario, testData };
    }
    let parsed: { steps?: unknown; testData?: unknown };
    try {
      parsed = JSON.parse(structuredText);
    } catch (e) {
      throw new Error(`Invalid JSON: ${(e as Error).message}`);
    }
    if (!Array.isArray(parsed.steps)) throw new Error('The JSON must have a "steps" array.');
    return { ...base, steps: parsed.steps as TestExecutionInput["steps"],
             testData: (parsed.testData ?? {}) as Record<string, string> };
  }

  async function run() {
    setError(null);
    let body: TestExecutionInput;
    try { body = buildBody(); } catch (e) { setError((e as Error).message); return; }
    setStarting(true);
    try {
      const { executionId } = await api.create(body, llm);
      setResult(null);
      startPolling(executionId);
      loadHistory();
    } catch (e) {
      const err = e as ApiError;
      setError(err.status === 501 ? `Not available yet: ${err.message}` : err.message);
    } finally {
      setStarting(false);
    }
  }

  async function stop() {
    if (!result) return;
    setStopping(true);
    try { await api.stop(result.executionId); } catch (e) { setError((e as Error).message); setStopping(false); }
  }

  const running = result != null && !TERMINAL.includes(result.status);

  return (
    <Box sx={{ minHeight: "100vh", bgcolor: "grey.50" }}>
      <AppBar position="static" color="default" elevation={1}>
        <Toolbar sx={{ gap: 2, flexWrap: "wrap", py: 1 }}>
          <Typography variant="h6" sx={{ flex: 1, minWidth: 240 }}>Mobile Autonomous Execution</Typography>
          <FormControl size="small" sx={{ minWidth: 220 }}>
            <InputLabel>GenAI Server</InputLabel>
            <Select label="GenAI Server" value={llm.provider}
                    onChange={(e) => selectProvider(e.target.value as LlmConfig["provider"])}>
              <MenuItem value="none">None — structured steps</MenuItem>
              <MenuItem value="azure">Azure OpenAI</MenuItem>
              <MenuItem value="gemini">Gemini</MenuItem>
            </Select>
          </FormControl>
          {llm.provider === "azure" && (
            <>
              <TextField size="small" label="Endpoint" value={llm.endpoint} sx={{ width: 300 }}
                         placeholder="https://<resource>.openai.azure.com/"
                         slotProps={{ inputLabel: { shrink: true } }}
                         onChange={(e) => setLlm({ ...llm, endpoint: e.target.value })} />
              <TextField size="small" label="API version" value={llm.apiVersion} sx={{ width: 170 }}
                         placeholder="YYYY-MM-DD[-preview]"
                         slotProps={{ inputLabel: { shrink: true } }}
                         onChange={(e) => setLlm({ ...llm, apiVersion: e.target.value })} />
            </>
          )}
          <TextField size="small" label={llm.provider === "azure" ? "Deployment" : "Model"} value={llm.model}
                     disabled={llm.provider === "none"}
                     placeholder={llm.provider === "azure" ? "deployment name" : llm.provider === "gemini" ? "model name" : ""}
                     slotProps={{ inputLabel: { shrink: llm.provider !== "none" || !!llm.model } }}
                     onChange={(e) => setLlm({ ...llm, model: e.target.value })} sx={{ width: 170 }} />
          {/* A chave LLM fica só em memória (nunca em localStorage). */}
          <TextField size="small" label="LLM API key" type="password" value={llm.apiKey}
                     disabled={llm.provider === "none"} autoComplete="off"
                     onChange={(e) => setLlm({ ...llm, apiKey: e.target.value })} sx={{ width: 180 }} />
          <Tooltip title="Save provider, endpoint, API version and deployment in this browser. The API key is never saved.">
            <span>
              <Button variant="outlined" startIcon={<SaveIcon />} onClick={saveLlmSettings}
                      disabled={llm.provider === "none"}>Save</Button>
            </span>
          </Tooltip>
          <Tooltip title="Remove the saved settings from this browser">
            <Button color="inherit" onClick={clearLlmSettings} sx={{ minWidth: 0 }}><DeleteOutlineIcon /></Button>
          </Tooltip>
        </Toolbar>
      </AppBar>
      <Snackbar open={savedMsg != null} autoHideDuration={3500} onClose={() => setSavedMsg(null)}
                message={savedMsg} anchorOrigin={{ vertical: "bottom", horizontal: "center" }} />

      <Container maxWidth="lg" sx={{ py: 3 }}>
        <Stack spacing={2}>
          {!api.hasKey && (
            <Alert severity="warning">VITE_QAGENT_API_KEY is not set (frontend/.env.local).</Alert>
          )}

          <Paper variant="outlined" sx={{ p: 2 }}>
            <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 2 }}>Configuration</Typography>
            <Stack direction={{ xs: "column", md: "row" }} spacing={2}>
              <FormControl size="small" sx={{ minWidth: 140 }}>
                <InputLabel>Platform</InputLabel>
                <Select label="Platform" value="android">
                  <MenuItem value="android">Android</MenuItem>
                  <MenuItem value="ios" disabled>iOS (not supported yet)</MenuItem>
                </Select>
              </FormControl>
              <Stack direction="row" spacing={0.5} sx={{ alignItems: "center", minWidth: 260 }}>
                <FormControl size="small" fullWidth>
                  <InputLabel>Device</InputLabel>
                  <Select label="Device" value={deviceUdid} onChange={(e) => setDeviceUdid(e.target.value)}>
                    {devices.filter((d) => d.platform === "android").map((d) => (
                      <MenuItem key={d.udid ?? ""} value={d.udid ?? ""}>
                        {d.udid} · {d.type}{d.model ? ` · ${d.model}` : ""}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
                <Tooltip title="Refresh devices">
                  <Button onClick={loadDevices} sx={{ minWidth: 0 }}><RefreshIcon /></Button>
                </Tooltip>
              </Stack>
              <TextField size="small" label="App package (optional)" placeholder="empty = start on home screen"
                         value={appPackage} onChange={(e) => setAppPackage(e.target.value)} sx={{ flex: 1 }} />
              <TextField size="small" label="App activity" value={appActivity}
                         onChange={(e) => setAppActivity(e.target.value)} sx={{ flex: 1 }} />
              <TextField size="small" label="APK path (optional)" value={appPath}
                         onChange={(e) => setAppPath(e.target.value)} sx={{ flex: 1 }} />
            </Stack>
            <Stack direction="row" spacing={3} sx={{ mt: 1.5, alignItems: "center", flexWrap: "wrap" }}>
              <FormControlLabel label="Stop on failure"
                control={<Switch checked={stopOnFailure} onChange={(e) => setStopOnFailure(e.target.checked)} />} />
              <FormControl size="small" sx={{ minWidth: 180 }}>
                <InputLabel>Screenshots</InputLabel>
                <Select label="Screenshots" value={screenshots}
                        onChange={(e) => setScreenshots(e.target.value as typeof screenshots)}>
                  <MenuItem value="every_step">Every step</MenuItem>
                  <MenuItem value="on_failure">On failure</MenuItem>
                  <MenuItem value="none">None</MenuItem>
                </Select>
              </FormControl>
              <Tooltip title="Packages whose data is cleared before the test (clean, repeatable state). Destructive for those apps.">
                <TextField size="small" label="Reset apps (optional)" value={resetApps} sx={{ flex: 1, minWidth: 260 }}
                           placeholder="com.example.app, com.other.app"
                           onChange={(e) => setResetApps(e.target.value)} />
              </Tooltip>
            </Stack>
          </Paper>

          <Paper variant="outlined" sx={{ p: 2 }}>
            <Tabs value={mode} onChange={(_, v) => setMode(v)} sx={{ mb: 2 }} variant="scrollable">
              <Tab value="manual" label="Manual test steps" />
              <Tab value="gherkin" label="Gherkin" />
              <Tab value="structured" label="Steps" />
            </Tabs>

            {mode === "manual" && (
              <>
                <Alert severity="info" sx={{ mb: 2 }}>
                  Needs a GenAI Server. The LLM first splits the text into Given/When/Then steps (1 call),
                  then executes each step on the device.
                </Alert>
                <TextField label="Enter your manual test steps" multiline minRows={5} fullWidth
                           placeholder="e.g. Open the app X, do … and validate that …  (several apps: “go to app X, … then go to app Y, …”)"
                           value={manualText} onChange={(e) => setManualText(e.target.value)} />
                <TextField label="Test data (JSON, optional)" multiline minRows={2} fullWidth sx={{ mt: 2,
                           "& textarea": { fontFamily: "monospace", fontSize: 13 } }}
                           value={testDataText} onChange={(e) => setTestDataText(e.target.value)}
                           placeholder={'{"username": "...", "password": "{{secret:name}}"}'}
                           helperText="Referenced in the steps as {{testData.<key>}}. Secrets: {{secret:name}} → server env QAGENT_SECRET_NAME. The LLM never sees secret values." />
              </>
            )}
            {mode === "gherkin" && (
              <>
                <Alert severity="info" sx={{ mb: 2 }}>
                  Needs a GenAI Server. Each Given/When/Then line becomes one step (no extra LLM call to
                  split them).
                </Alert>
                <TextField label="Gherkin scenario" multiline minRows={5} fullWidth
                           placeholder={["Scenario: …", "Given …", "When …", "Then …"].join("\n")}
                           value={gherkinText} onChange={(e) => setGherkinText(e.target.value)}
                           sx={{ "& textarea": { fontFamily: "monospace" } }} />
                <TextField label="Test data (JSON, optional)" multiline minRows={2} fullWidth sx={{ mt: 2,
                           "& textarea": { fontFamily: "monospace", fontSize: 13 } }}
                           value={testDataText} onChange={(e) => setTestDataText(e.target.value)}
                           placeholder={'{"username": "...", "password": "{{secret:name}}"}'}
                           helperText="Referenced in the steps as {{testData.<key>}}. Secrets: {{secret:name}} → server env QAGENT_SECRET_NAME. The LLM never sees secret values." />
              </>
            )}
            {mode === "structured" && (
              <>
                <TextField label='{"steps": [...], "testData": {...}}' multiline minRows={12} maxRows={24}
                           placeholder={'{\n  "steps": [\n    {"action": "ai", "text": "Open the app X and ..."},\n'
                             + '    {"action": "tap", "locator": {"strategy": "accessibility id", "value": "..."}}\n'
                             + '  ],\n  "testData": {"user": "...", "password": "{{secret:name}}"}\n}'}
                           fullWidth value={structuredText} onChange={(e) => setStructuredText(e.target.value)}
                           sx={{ "& textarea": { fontFamily: "monospace", fontSize: 13 } }} />
                <Typography variant="caption" sx={{ color: "text.secondary", display: "block", mt: 1 }}>
                  Actions: ai (natural language, needs a GenAI Server), tap, type, scroll_to, assert_visible,
                  assert_text, back, wait. Secrets:
                  {" "}<code>{"{{secret:name}}"}</code> → server env <code>QAGENT_SECRET_NAME</code>.
                </Typography>
              </>
            )}

            <Stack direction="row" sx={{ mt: 2, alignItems: "center", gap: 2 }}>
              <Button variant="contained" size="large" startIcon={<PlayArrowIcon />}
                      onClick={run} disabled={starting || running}>
                {starting ? "Starting…" : "Execute"}
              </Button>
              {running && <Typography variant="body2" sx={{ color: "text.secondary" }}>
                An execution is in progress.</Typography>}
            </Stack>
          </Paper>

          {error && <Alert severity="error" onClose={() => setError(null)} sx={{ whiteSpace: "pre-wrap" }}>{error}</Alert>}

          {result && <ResultPanel result={result} stopping={stopping} onStop={stop} />}

          {history.length > 0 && (
            <Paper variant="outlined" sx={{ p: 2 }}>
              <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 1 }}>Recent executions</Typography>
              <Stack spacing={0.5}>
                {history.slice(0, 10).map((h) => (
                  <Stack key={h.executionId} direction="row" spacing={1.5}
                         sx={{ alignItems: "center", cursor: "pointer", py: 0.5, px: 1, borderRadius: 1,
                               "&:hover": { bgcolor: "action.hover" },
                               bgcolor: h.executionId === result?.executionId ? "action.selected" : undefined }}
                         onClick={() => { setStopping(false); startPolling(h.executionId); }}>
                    <Chip size="small" label={EXEC_LABEL[h.status].label} color={EXEC_LABEL[h.status].color}
                          sx={{ minWidth: 84 }} />
                    <Typography variant="body2" sx={{ fontFamily: "monospace" }}>{h.executionId}</Typography>
                    <Typography variant="body2" sx={{ color: "text.secondary" }}>
                      {new Date(h.createdAt).toLocaleString()}
                    </Typography>
                    <Typography variant="body2" noWrap sx={{ color: "text.secondary", flex: 1, minWidth: 0 }}>
                      {h.summary}
                    </Typography>
                  </Stack>
                ))}
              </Stack>
            </Paper>
          )}
        </Stack>
      </Container>
    </Box>
  );
}
