import { useState, useEffect, useCallback, useRef } from "react";
import {
  ModelSidebar,
  type Model,
  type DashboardView,
} from "./components/ModelSidebar";
import { ControlDashboard } from "./components/ControlDashboard";
import {
  listModels,
  pingBackend,
  toggleModel as toggleModelApi,
  getDisabledModels,
} from "./services/llm";
import { useServerLogs } from "./services/serverLogs";

// ── Model definitions matching the Python backend's model registry ───

const MODEL_DEFS: (Omit<Model, "status"> & { modelTag: string })[] = [
  {
    id: "deepseek-8b",
    name: "DeepSeek R1 8B",
    modelTag: "deepseek-r1:8b",
    category: "reasoning",
    vram: 4.9,
    speed: "medium",
    description: "Proposal decomposition and reasoning",
    supportsVision: false,
  },
  {
    id: "qwen3.5-2b",
    name: "Qwen3.5 2B",
    modelTag: "qwen3.5:2b",
    category: "fast",
    vram: 1.4,
    speed: "fast",
    description: "Lightweight eFlow tutorial candidate",
    supportsVision: false,
  },
  {
    id: "qwen3.5-4b",
    name: "Qwen3.5 4B",
    modelTag: "qwen3.5:4b",
    category: "chat",
    vram: 2.7,
    speed: "medium",
    description: "Higher-capacity eFlow tutorial candidate",
    supportsVision: false,
  },
];

export default function App() {
  const statusInFlight = useRef(false);
  const [view, setView] = useState<DashboardView>("overview");
  const [models, setModels] = useState<Model[]>(() =>
    MODEL_DEFS.map((d) => ({ ...d, status: "unknown" as const })),
  );
  const [backendOnline, setBackendOnline] = useState(false);
  const [enabledModels, setEnabledModels] = useState<Set<string>>(
    () => new Set(MODEL_DEFS.map((d) => d.id)), // all enabled by default
  );

  // ── Server logs ─────────────────────────────────────────────────────
  const { logs, serverStatus, usageStats, clearLogs } = useServerLogs(true);

  // ── Poll backend for model availability ─────────────────────────────
  const refreshStatus = useCallback(async () => {
    if (statusInFlight.current) return;
    statusInFlight.current = true;
    const online = await pingBackend();
    setBackendOnline(online);
    if (!online) {
      setModels(MODEL_DEFS.map((d) => ({ ...d, status: "unknown" as const })));
      statusInFlight.current = false;
      return;
    }

    try {
      const [available, disabled] = await Promise.all([
        listModels(),
        getDisabledModels(),
      ]);

      setEnabledModels(
        new Set(
          MODEL_DEFS.filter((d) => !disabled.includes(d.modelTag)).map(
            (d) => d.id,
          ),
        ),
      );

      // Check which models have been downloaded
      const downloadedNames = new Set(
        available.filter((m) => m.downloaded).map((m) => m.name),
      );

      setModels(
        MODEL_DEFS.map((d) => {
          const isDownloaded = downloadedNames.has(d.modelTag);

          return {
            ...d,
            status: isDownloaded ? ("loaded" as const) : ("unloaded" as const),
            vram:
              +(
                available.find((m) => m.name === d.modelTag)?.size ??
                d.vram * 1e9
              ) / 1e9,
          };
        }),
      );
    } catch (err) {
      console.error("Failed to refresh models:", err);
    } finally {
      statusInFlight.current = false;
    }
  }, []);

  useEffect(() => {
    refreshStatus();
    const interval = setInterval(() => {
      if (!document.hidden) void refreshStatus();
    }, 10_000);
    return () => clearInterval(interval);
  }, [refreshStatus]);

  const handleToggleModel = async (modelId: string) => {
    const def = MODEL_DEFS.find((d) => d.id === modelId);
    if (!def) return;

    const newEnabled = !enabledModels.has(modelId);

    // Optimistic UI update
    setEnabledModels((prev) => {
      const next = new Set(prev);
      if (newEnabled) {
        next.add(modelId);
      } else {
        next.delete(modelId);
      }
      return next;
    });

    // Tell the backend
    const result = await toggleModelApi(def.modelTag, newEnabled);
    if (!result.ok) {
      // Revert on failure
      setEnabledModels((prev) => {
        const next = new Set(prev);
        if (newEnabled) {
          next.delete(modelId);
        } else {
          next.add(modelId);
        }
        return next;
      });
    }
  };

  return (
    <div className="server-app light-app-theme">
      <ModelSidebar view={view} onViewChange={setView} />
      <ControlDashboard
        view={view}
        onViewChange={setView}
        backendOnline={backendOnline}
        onToggleModel={handleToggleModel}
        logs={logs}
        serverStatus={serverStatus}
        usageStats={usageStats}
        onClearLogs={clearLogs}
        models={models}
        enabledModels={enabledModels}
      />
    </div>
  );
}
