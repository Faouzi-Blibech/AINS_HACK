import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { postAgentRun, postAgentImport, postAgentImportUpload } from "../api/client.js";

// Provider presets matching the backend _PROVIDER_PRESETS
const PRESETS = {
  groq: {
    label: "Groq (recommended)",
    base_url: "https://api.groq.com/openai/v1",
    default_model: "llama-3.3-70b-versatile",
  },
  nvidia_nim: {
    label: "NVIDIA NIM",
    base_url: "https://integrate.api.nvidia.com/v1",
    default_model: "meta/llama-3.1-8b-instruct",
  },
  huggingface: {
    label: "Hugging Face",
    base_url: "https://router.huggingface.co/v1",
    default_model: "meta-llama/Llama-3.1-8B-Instruct",
  },
  custom: {
    label: "Custom",
    base_url: "",
    default_model: "",
  },
};

const PRESET_KEYS = Object.keys(PRESETS);

// ---------------------------------------------------------------------------
// Shared small components
// ---------------------------------------------------------------------------

function SectionLabel({ children }) {
  return (
    <div
      style={{
        font: "600 9.5px var(--mono)",
        letterSpacing: ".14em",
        color: "var(--fg2)",
        textTransform: "uppercase",
        marginBottom: 10,
      }}
    >
      {children}
    </div>
  );
}

function FieldLabel({ children, htmlFor }) {
  return (
    <label
      htmlFor={htmlFor}
      style={{
        display: "block",
        font: "500 11.5px var(--ui)",
        color: "var(--fg2)",
        marginBottom: 5,
      }}
    >
      {children}
    </label>
  );
}

function TextInput({ id, value, onChange, placeholder, type, readOnly, style: extraStyle }) {
  return (
    <input
      id={id}
      type={type || "text"}
      value={value}
      onChange={onChange}
      placeholder={placeholder}
      readOnly={readOnly}
      autoComplete="off"
      style={{
        width: "100%",
        boxSizing: "border-box",
        background: readOnly ? "var(--bg2)" : "var(--bg1)",
        border: "1px solid var(--bd2)",
        borderRadius: 9,
        padding: "9px 12px",
        font: "450 13px var(--mono)",
        color: readOnly ? "var(--fg2)" : "var(--fg0)",
        outline: "none",
        ...extraStyle,
      }}
    />
  );
}

function ErrorBanner({ message }) {
  return (
    <div
      style={{
        background: "var(--fail-dim)",
        border: "1px solid var(--fail)",
        borderRadius: 10,
        padding: "12px 16px",
        font: "450 12.5px var(--ui)",
        color: "var(--fail)",
        display: "flex",
        alignItems: "flex-start",
        gap: 9,
        marginTop: 14,
      }}
    >
      <svg
        width="15"
        height="15"
        viewBox="0 0 16 16"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
        style={{ flex: "none", marginTop: 1 }}
      >
        <path d="M8 1.5l6.5 11.5H1.5z" />
        <path d="M8 6.5v3" />
        <circle cx="8" cy="11.5" r=".75" fill="currentColor" stroke="none" />
      </svg>
      <span style={{ flex: 1 }}>{message}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Panel A: Quick test (hosted model)
// ---------------------------------------------------------------------------

function QuickTestPanel() {
  const navigate = useNavigate();

  const [provider, setProvider] = useState("groq");
  const [baseUrl, setBaseUrl] = useState(PRESETS.groq.base_url);
  const [model, setModel] = useState(PRESETS.groq.default_model);
  const [apiKey, setApiKey] = useState("");
  const [task, setTask] = useState(
    "Look up the current status and owner of project Alpha, then submit a one-sentence summary of its health."
  );
  const [running, setRunning] = useState(false);
  const [error, setError] = useState(null);

  function handleProviderChange(e) {
    const key = e.target.value;
    setProvider(key);
    const preset = PRESETS[key];
    setBaseUrl(preset.base_url);
    setModel(preset.default_model);
    setError(null);
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);
    setRunning(true);
    try {
      const body = {
        model,
        api_key: apiKey,
        task,
      };
      if (provider !== "custom") {
        body.provider = provider;
      } else {
        body.base_url = baseUrl;
      }
      const result = await postAgentRun(body);
      navigate(`/runs/${result.run_id}`);
    } catch (err) {
      // Never echo back the api key; show a sanitised message only
      const raw = err.message ?? "Run failed.";
      // Strip any accidental key echoes (should not happen, defensive only)
      setError(raw.replace(apiKey, "[key]") || "Run failed.");
    } finally {
      setRunning(false);
    }
  }

  const isCustom = provider === "custom";

  return (
    <div
      style={{
        background: "var(--bg1)",
        border: "1px solid var(--bd)",
        borderRadius: 16,
        padding: "24px 26px",
        boxShadow: "var(--shadow-sm)",
        animation: "fadeup .2s ease",
      }}
    >
      <SectionLabel>Quick test</SectionLabel>
      <p
        style={{
          margin: "0 0 20px",
          font: "450 12.5px var(--ui)",
          color: "var(--fg2)",
          lineHeight: 1.6,
        }}
      >
        Run a live agent call through a hosted model and record the trace. Runs need a model API key.
        Groq is recommended for reliable tool calling (free tier); NVIDIA NIM and Hugging Face also work.
        The bundled demo still replays with no key.
      </p>

      <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        {/* Provider selector */}
        <div>
          <FieldLabel htmlFor="provider-select">Provider preset</FieldLabel>
          <select
            id="provider-select"
            value={provider}
            onChange={handleProviderChange}
            disabled={running}
            style={{
              width: "100%",
              background: "var(--bg1)",
              border: "1px solid var(--bd2)",
              borderRadius: 9,
              padding: "9px 12px",
              font: "450 13px var(--ui)",
              color: "var(--fg0)",
              outline: "none",
              cursor: running ? "not-allowed" : "pointer",
            }}
          >
            {PRESET_KEYS.map((k) => (
              <option key={k} value={k}>
                {PRESETS[k].label}
              </option>
            ))}
          </select>
        </div>

        {/* Base URL: read-only for presets, editable for custom */}
        <div>
          <FieldLabel htmlFor="base-url-input">Base URL</FieldLabel>
          <TextInput
            id="base-url-input"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder="https://..."
            readOnly={!isCustom}
          />
        </div>

        {/* Model */}
        <div>
          <FieldLabel htmlFor="model-input">Model ID</FieldLabel>
          <TextInput
            id="model-input"
            value={model}
            onChange={(e) => setModel(e.target.value)}
            placeholder="e.g. meta/llama-3.1-8b-instruct"
          />
        </div>

        {/* API key */}
        <div>
          <FieldLabel htmlFor="api-key-input">API key</FieldLabel>
          <TextInput
            id="api-key-input"
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="sk-..."
          />
        </div>

        {/* Task */}
        <div>
          <FieldLabel htmlFor="task-input">Task</FieldLabel>
          <textarea
            id="task-input"
            value={task}
            onChange={(e) => setTask(e.target.value)}
            placeholder="Describe the task for the agent..."
            rows={4}
            style={{
              width: "100%",
              boxSizing: "border-box",
              background: "var(--bg1)",
              border: "1px solid var(--bd2)",
              borderRadius: 9,
              padding: "9px 12px",
              font: "450 13px var(--ui)",
              color: "var(--fg0)",
              outline: "none",
              resize: "vertical",
              lineHeight: 1.55,
            }}
          />
        </div>

        {error && <ErrorBanner message={error} />}

        <div style={{ display: "flex", alignItems: "center", gap: 14, marginTop: 4 }}>
          <button
            type="submit"
            disabled={running || !model.trim() || !task.trim() || !apiKey.trim()}
            style={{
              background: running ? "var(--bg3)" : "var(--accent)",
              color: running ? "var(--fg2)" : "var(--bg0)",
              border: "none",
              borderRadius: 10,
              padding: "10px 22px",
              font: "600 13px var(--ui)",
              cursor: running ? "not-allowed" : "pointer",
              display: "flex",
              alignItems: "center",
              gap: 8,
              transition: "background 0.15s",
            }}
          >
            {running && (
              <svg
                width="14"
                height="14"
                viewBox="0 0 14 14"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                style={{ animation: "spin 0.8s linear infinite" }}
              >
                <circle cx="7" cy="7" r="5" strokeOpacity="0.3" />
                <path d="M7 2a5 5 0 015 5" strokeLinecap="round" />
              </svg>
            )}
            {running ? "Running..." : "Record run"}
          </button>
          {running && (
            <span
              style={{
                font: "450 12px var(--ui)",
                color: "var(--fg2)",
              }}
            >
              Running live agent, this may take a moment...
            </span>
          )}
        </div>
      </form>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Panel B: Import agent
// ---------------------------------------------------------------------------

const SKIP_SEGMENTS = new Set([
  "node_modules", ".git", ".venv", "venv", "__pycache__", "dist", "build", ".next",
]);
const MAX_UPLOAD_FILE = 5 * 1024 * 1024; // 5 MB per file (client skip)

function keepUploadFile(f) {
  const rel = f.webkitRelativePath || f.name;
  if (rel.split("/").some((s) => SKIP_SEGMENTS.has(s))) return false;
  if (f.size > MAX_UPLOAD_FILE) return false;
  return true;
}

function ImportPanel() {
  const navigate = useNavigate();
  const [source, setSource] = useState("");
  const [ref, setRef] = useState("");
  const [command, setCommand] = useState("");
  const [task, setTask] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [extraEnv, setExtraEnv] = useState("");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState(null);
  const [mode, setMode] = useState("path"); // "path" | "upload"
  const [files, setFiles] = useState([]);

  function buildEnv() {
    const env = {};
    if (apiKey.trim()) env.OPENAI_API_KEY = apiKey.trim();
    extraEnv.split("\n").forEach((line) => {
      const i = line.indexOf("=");
      if (i > 0) {
        const k = line.slice(0, i).trim();
        const v = line.slice(i + 1).trim();
        if (k) env[k] = v;
      }
    });
    return env;
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);
    setRunning(true);
    try {
      const env = buildEnv();
      let result;
      if (mode === "upload") {
        const kept = files.filter(keepUploadFile);
        if (!kept.length) throw new Error("Select a folder with at least one file to upload.");
        const fd = new FormData();
        for (const f of kept) {
          const rel = f.webkitRelativePath || f.name;
          // Strip the top-level folder so the workspace root is the agent root.
          const inner = rel.includes("/") ? rel.split("/").slice(1).join("/") : rel;
          fd.append("files", f, inner || f.name);
        }
        if (command.trim()) fd.append("command", command.trim());
        if (task.trim()) fd.append("task", task.trim());
        if (Object.keys(env).length) fd.append("env", JSON.stringify(env));
        result = await postAgentImportUpload(fd);
      } else {
        const body = { source };
        if (ref.trim()) body.ref = ref.trim();
        if (command.trim()) body.command = command.trim();
        if (task.trim()) body.task = task.trim();
        if (Object.keys(env).length) body.env = env;
        result = await postAgentImport(body);
      }
      navigate(`/runs/${result.run_id}`);
    } catch (err) {
      const raw = err.message ?? "Import failed.";
      setError(apiKey ? raw.replaceAll(apiKey, "[key]") : raw);
    } finally {
      setRunning(false);
    }
  }

  return (
    <div
      style={{
        background: "var(--bg1)",
        border: "1px solid var(--bd)",
        borderRadius: 16,
        padding: "24px 26px",
        boxShadow: "var(--shadow-sm)",
        animation: "fadeup .25s ease",
      }}
    >
      <SectionLabel>Import agent</SectionLabel>
      <p
        style={{
          margin: "0 0 20px",
          font: "450 12.5px var(--ui)",
          color: "var(--fg2)",
          lineHeight: 1.6,
        }}
      >
        Paste a git URL or a local path. Cassette clones it, runs it in an isolated
        container with recording wired in automatically, and captures the run. No
        proxy setup needed.
      </p>

      <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <div style={{ display: "flex", gap: 8 }}>
          {["path", "upload"].map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => { setMode(m); setError(null); }}
              style={{
                flex: 1,
                background: mode === m ? "var(--accent)" : "var(--bg2)",
                color: mode === m ? "var(--bg0)" : "var(--fg2)",
                border: "1px solid var(--bd2)",
                borderRadius: 9,
                padding: "8px 10px",
                font: "600 12px var(--ui)",
                cursor: "pointer",
              }}
            >
              {m === "path" ? "Git URL / path" : "Upload folder"}
            </button>
          ))}
        </div>

        {mode === "path" ? (
          <>
            <div>
              <FieldLabel htmlFor="src">Repo URL or local path</FieldLabel>
              <TextInput
                id="src"
                value={source}
                onChange={(e) => setSource(e.target.value)}
                placeholder="https://github.com/you/agent.git  or  /path/to/agent"
              />
            </div>
            <div>
              <FieldLabel htmlFor="ref">Branch / ref (optional)</FieldLabel>
              <TextInput id="ref" value={ref} onChange={(e) => setRef(e.target.value)} placeholder="leave blank for the default branch" />
            </div>
          </>
        ) : (
          <div>
            <FieldLabel htmlFor="folder">Agent folder</FieldLabel>
            <label
              htmlFor="folder"
              style={{
                display: "inline-block",
                cursor: "pointer",
                background: "var(--bg2)",
                border: "1px solid var(--bd2)",
                borderRadius: 9,
                padding: "9px 14px",
                font: "600 12px var(--ui)",
                color: "var(--fg1)",
              }}
            >
              {files.length ? "Change folder…" : "Browse folder…"}
            </label>
            <input
              id="folder"
              type="file"
              webkitdirectory=""
              directory=""
              multiple
              onChange={(e) => setFiles(Array.from(e.target.files))}
              style={{ display: "none" }}
            />
            <p style={{ margin: "6px 2px 0", font: "450 11px var(--ui)", color: "var(--fg2)", lineHeight: 1.5 }}>
              {files.filter(keepUploadFile).length
                ? `${files.filter(keepUploadFile).length} files selected (node_modules, .git, .venv, build dirs skipped).`
                : "Pick your agent's folder. Junk dirs and files over 5 MB are skipped."}
            </p>
          </div>
        )}

        <div>
          <FieldLabel htmlFor="cmd">Run command (optional)</FieldLabel>
          <TextInput
            id="cmd"
            value={command}
            onChange={(e) => setCommand(e.target.value)}
            placeholder="python main.py"
          />
        </div>

        <div>
          <FieldLabel htmlFor="task">Task / message to send (optional)</FieldLabel>
          <TextInput
            id="task"
            value={task}
            onChange={(e) => setTask(e.target.value)}
            placeholder="e.g. what is the weather in London"
          />
          <p style={{ margin: "6px 2px 0", font: "450 11px var(--ui)", color: "var(--fg2)", lineHeight: 1.5 }}>
            For interactive agents (a chat / prompt loop), this is sent as the
            agent's input so it actually runs and produces a trace. Leave blank
            for agents that run on their own.
          </p>
        </div>

        <div>
          <FieldLabel htmlFor="key">Agent API key (optional)</FieldLabel>
          <TextInput
            id="key"
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="sk-..."
          />
          <p style={{ margin: "6px 2px 0", font: "450 11px var(--ui)", color: "var(--fg2)", lineHeight: 1.5 }}>
            Sent to the agent as OPENAI_API_KEY.
          </p>
        </div>

        <div>
          <FieldLabel htmlFor="env">Extra environment variables (optional)</FieldLabel>
          <textarea
            id="env"
            value={extraEnv}
            onChange={(e) => setExtraEnv(e.target.value)}
            placeholder={"One per line, KEY=VALUE\ne.g. WEATHER_API_KEY=...."}
            rows={3}
            spellCheck={false}
            style={{
              width: "100%",
              boxSizing: "border-box",
              background: "var(--bg2)",
              border: "1px solid var(--bd)",
              borderRadius: 10,
              padding: "10px 12px",
              color: "var(--fg0)",
              font: "450 12.5px var(--mono)",
              resize: "vertical",
            }}
          />
          <p style={{ margin: "6px 2px 0", font: "450 11px var(--ui)", color: "var(--fg2)", lineHeight: 1.5 }}>
            For agents that need more than one key (the weather example needs
            WEATHER_API_KEY too). Never stored; passed to the agent for this run only.
          </p>
        </div>

        {error && <ErrorBanner message={error} />}

        <div style={{ display: "flex", alignItems: "center", gap: 14, marginTop: 4 }}>
          <button
            type="submit"
            disabled={running || (mode === "path" ? !source.trim() : !files.length)}
            style={{
              background: running ? "var(--bg3)" : "var(--accent)",
              color: running ? "var(--fg2)" : "var(--bg0)",
              border: "none",
              borderRadius: 10,
              padding: "10px 22px",
              font: "600 13px var(--ui)",
              cursor: running ? "not-allowed" : "pointer",
            }}
          >
            {running ? "Importing..." : "Import & record"}
          </button>
          {running && (
            <span style={{ font: "450 12px var(--ui)", color: "var(--fg2)" }}>
              Cloning, building, and recording, this may take a moment...
            </span>
          )}
        </div>
      </form>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page root
// ---------------------------------------------------------------------------

export default function ConnectAgent() {
  return (
    <div
      style={{
        flex: 1,
        overflowY: "auto",
        overflowX: "hidden",
        padding: "28px 28px 48px",
      }}
    >
      {/* Page header */}
      <div style={{ marginBottom: 26 }}>
        <h1
          style={{
            margin: 0,
            font: "700 22px var(--ui)",
            letterSpacing: "-.02em",
            color: "var(--fg0)",
          }}
        >
          Connect agent
        </h1>
        <p
          style={{
            margin: "5px 0 0",
            font: "450 12.5px var(--ui)",
            color: "var(--fg2)",
          }}
        >
          Run a quick test with a hosted model, or import a repo (git URL or local path) to record it automatically.
        </p>
      </div>

      {/* Two-panel layout */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(420px, 1fr))",
          gap: 18,
          alignItems: "start",
        }}
      >
        <QuickTestPanel />
        <ImportPanel />
      </div>

      <style>{`
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
        @keyframes fadeup {
          from { opacity: 0; transform: translateY(8px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  );
}
