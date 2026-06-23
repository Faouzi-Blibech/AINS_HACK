import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { postAgentRun, getConnectInfo } from "../api/client.js";

// Provider presets matching the backend _PROVIDER_PRESETS
const PRESETS = {
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
  groq: {
    label: "Groq",
    base_url: "https://api.groq.com/openai/v1",
    default_model: "llama3-8b-8192",
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

function CopyButton({ text }) {
  const [copied, setCopied] = useState(false);

  function handleCopy() {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    });
  }

  return (
    <button
      onClick={handleCopy}
      title="Copy to clipboard"
      style={{
        position: "absolute",
        top: 10,
        right: 10,
        background: copied ? "var(--pass-dim)" : "var(--bg3)",
        border: "1px solid var(--bd2)",
        borderRadius: 7,
        padding: "4px 10px",
        font: "600 10px var(--mono)",
        color: copied ? "var(--pass)" : "var(--fg2)",
        cursor: "pointer",
        letterSpacing: ".06em",
        transition: "background 0.15s, color 0.15s",
      }}
    >
      {copied ? "COPIED" : "COPY"}
    </button>
  );
}

function MonoBlock({ content }) {
  return (
    <div style={{ position: "relative" }}>
      <pre
        style={{
          margin: 0,
          background: "var(--bg0)",
          border: "1px solid var(--bd)",
          borderRadius: 10,
          padding: "14px 46px 14px 14px",
          font: "450 12px var(--mono)",
          color: "var(--fg1)",
          whiteSpace: "pre-wrap",
          wordBreak: "break-all",
          lineHeight: 1.65,
          overflowX: "auto",
        }}
      >
        {content}
      </pre>
      <CopyButton text={content} />
    </div>
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

  const [provider, setProvider] = useState("nvidia_nim");
  const [baseUrl, setBaseUrl] = useState(PRESETS.nvidia_nim.base_url);
  const [model, setModel] = useState(PRESETS.nvidia_nim.default_model);
  const [apiKey, setApiKey] = useState("");
  const [task, setTask] = useState("");
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
        Free tiers available on NVIDIA NIM and Hugging Face. The bundled demo still replays with no key.
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
// Panel B: Bring your own agent
// ---------------------------------------------------------------------------

const TABS = [
  { key: "http", label: "HTTP proxy" },
  { key: "mcp", label: "MCP" },
  { key: "sdk", label: "SDK" },
];

function BringYourOwnPanel() {
  const [info, setInfo] = useState(null);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState(null);
  const [activeTab, setActiveTab] = useState("http");

  useEffect(() => {
    setLoading(true);
    setFetchError(null);
    getConnectInfo()
      .then((data) => setInfo(data))
      .catch(() => setFetchError("Could not load connect info. Is the API server running?"))
      .finally(() => setLoading(false));
  }, []);

  function renderTabContent() {
    if (!info) return null;
    if (activeTab === "http") {
      const envBlock = Object.entries(info.http.env_vars)
        .map(([k, v]) => `export ${k}="${v}"`)
        .join("\n");
      const full = `${envBlock}\n\n${info.http.command}`;
      return (
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div>
            <div
              style={{
                font: "500 11.5px var(--ui)",
                color: "var(--fg2)",
                marginBottom: 8,
              }}
            >
              Set these env vars to route your agent through the Cassette proxy, then launch with the record command:
            </div>
            <MonoBlock content={full} />
          </div>
        </div>
      );
    }
    if (activeTab === "mcp") {
      return (
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div
            style={{
              font: "500 11.5px var(--ui)",
              color: "var(--fg2)",
              marginBottom: 4,
            }}
          >
            Wrap your MCP-enabled agent with the recorder to capture all tool calls automatically:
          </div>
          <MonoBlock content={info.mcp} />
        </div>
      );
    }
    if (activeTab === "sdk") {
      return (
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div
            style={{
              font: "500 11.5px var(--ui)",
              color: "var(--fg2)",
              marginBottom: 4,
            }}
          >
            Instrument your agent with the SDK hooks to record side-effecting tool calls inline:
          </div>
          <MonoBlock content={info.sdk} />
        </div>
      );
    }
    return null;
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
      <SectionLabel>Bring your own agent</SectionLabel>
      <p
        style={{
          margin: "0 0 20px",
          font: "450 12.5px var(--ui)",
          color: "var(--fg2)",
          lineHeight: 1.6,
        }}
      >
        Connect any external agent to Cassette. Choose the transport that matches your agent framework.
      </p>

      {loading && (
        <div
          style={{
            font: "450 12.5px var(--ui)",
            color: "var(--fg2)",
            padding: "18px 0",
          }}
        >
          Loading connect info...
        </div>
      )}

      {!loading && fetchError && <ErrorBanner message={fetchError} />}

      {!loading && !fetchError && info && (
        <>
          {/* Tab bar */}
          <div
            style={{
              display: "flex",
              gap: 4,
              marginBottom: 18,
              borderBottom: "1px solid var(--bd)",
              paddingBottom: 0,
            }}
          >
            {TABS.map((tab) => {
              const active = tab.key === activeTab;
              return (
                <button
                  key={tab.key}
                  onClick={() => setActiveTab(tab.key)}
                  style={{
                    background: "none",
                    border: "none",
                    borderBottom: active ? "2px solid var(--accent)" : "2px solid transparent",
                    padding: "8px 14px",
                    font: active ? "600 12.5px var(--ui)" : "450 12.5px var(--ui)",
                    color: active ? "var(--accent)" : "var(--fg2)",
                    cursor: "pointer",
                    marginBottom: "-1px",
                    transition: "color 0.12s",
                  }}
                >
                  {tab.label}
                </button>
              );
            })}
          </div>

          {/* Tab content */}
          {renderTabContent()}
        </>
      )}
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
          Run a quick test with a hosted model, or wire up your own agent via HTTP proxy, MCP, or the SDK.
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
        <BringYourOwnPanel />
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
