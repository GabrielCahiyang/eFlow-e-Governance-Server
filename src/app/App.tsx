import { useState, useEffect, useCallback } from 'react';
import { ModelSidebar, type Model } from './components/ModelSidebar';
import { ControlDashboard } from './components/ControlDashboard';
import { listModels, listRunningModels, pingBackend, toggleModel as toggleModelApi, getDisabledModels } from './services/llm';
import { useServerLogs } from './services/serverLogs';

// ── Model definitions matching the Python backend's model registry ───

const MODEL_DEFS: (Omit<Model, 'status'> & { modelTag: string })[] = [
  {
    id: 'llama3-8b',
    name: 'Llama 3 8B',
    modelTag: 'llama3:8b',
    category: 'chat',
    vram: 4.7,
    speed: 'medium',
    description: 'Chat / Edit',
    supportsVision: false,
  },
  {
    id: 'gemma-12b',
    name: 'Gemma 3 12B',
    modelTag: 'gemma3:12b',
    category: 'reasoning',
    vram: 7.2,
    speed: 'slow',
    description: 'Strong reasoning',
    supportsVision: false,
  },
  {
    id: 'deepseek-8b',
    name: 'DeepSeek 8B',
    modelTag: 'deepseek-r1:8b',
    category: 'reasoning',
    vram: 4.9,
    speed: 'medium',
    description: 'Advanced reasoning',
    supportsVision: false,
  },
  {
    id: 'qwen-7b',
    name: 'Qwen 7B',
    modelTag: 'qwen2.5:7b',
    category: 'chat',
    vram: 4.4,
    speed: 'medium',
    description: 'Balanced',
    supportsVision: false,
  },
  {
    id: 'phi3',
    name: 'Phi-3 Mini',
    modelTag: 'phi3:latest',
    category: 'fast',
    vram: 2.2,
    speed: 'fast',
    description: 'Fast responses',
    supportsVision: false,
  },
  {
    id: 'qwen-coder-1.5b',
    name: 'Qwen2.5-Coder 1.5B',
    modelTag: 'qwen2.5-coder:1.5b',
    category: 'coding',
    vram: 1.1,
    speed: 'fast',
    description: 'Autocomplete / Code',
    supportsVision: false,
  },
  {
    id: 'nomic-embed',
    name: 'Nomic Embed',
    modelTag: 'nomic-embed-text:latest',
    category: 'embedding',
    vram: 0.1,
    speed: 'fast',
    description: 'Embeddings',
    supportsVision: false,
  },
];

export default function App() {
  const [models, setModels] = useState<Model[]>(() =>
    MODEL_DEFS.map(d => ({ ...d, status: 'unloaded' as const }))
  );
  const [backendOnline, setBackendOnline] = useState(false);
  const [enabledModels, setEnabledModels] = useState<Set<string>>(
    () => new Set(MODEL_DEFS.map(d => d.id)) // all enabled by default
  );

  // ── Server logs ─────────────────────────────────────────────────────
  const { logs, serverStatus, usageStats, clearLogs } = useServerLogs(true);

  // ── Poll backend for model availability ─────────────────────────────
  const refreshStatus = useCallback(async () => {
    const online = await pingBackend();
    setBackendOnline(online);
    if (!online) {
      setModels(MODEL_DEFS.map(d => ({ ...d, status: 'unloaded' as const })));
      return;
    }

    try {
      const [available, running] = await Promise.all([
        listModels(),
        listRunningModels(),
      ]);

      const availableNames = new Set(available.map(m => m.name));
      const runningNames = new Set(running.map(m => m.name));

      // Check which models have been downloaded
      const downloadedNames = new Set(
        available
          .filter(m => (m as any).downloaded)
          .map(m => m.name)
      );

      setModels(MODEL_DEFS.map(d => {
        const isDownloaded = downloadedNames.has(d.modelTag);
        const isRunning = runningNames.has(d.modelTag) ||
          [...runningNames].some(n => n.startsWith(d.modelTag.split(':')[0]));

        return {
          ...d,
          status: isDownloaded ? 'loaded' as const : 'unloaded' as const,
          vram: isRunning
            ? +(running.find(r => r.name === d.modelTag || r.name.startsWith(d.modelTag.split(':')[0]))?.size_vram ?? d.vram * 1e9) / 1e9
            : d.vram,
        };
      }));
    } catch (err) {
      console.error('Failed to refresh models:', err);
    }
  }, []);

  useEffect(() => {
    refreshStatus();
    const interval = setInterval(refreshStatus, 10_000);
    return () => clearInterval(interval);
  }, [refreshStatus]);

  // Fetch disabled models on startup
  useEffect(() => {
    getDisabledModels().then((disabled) => {
      if (disabled.length > 0) {
        const disabledIds = new Set(
          MODEL_DEFS.filter(d => disabled.includes(d.modelTag)).map(d => d.id)
        );
        setEnabledModels(prev => {
          const next = new Set(prev);
          disabledIds.forEach(id => next.delete(id));
          return next;
        });
      }
    });
  }, []);

  // ── Model toggle — sync with backend ──────────────────────────────
  const handleToggleModel = async (modelId: string) => {
    const def = MODEL_DEFS.find(d => d.id === modelId);
    if (!def) return;

    const newEnabled = !enabledModels.has(modelId);

    // Optimistic UI update
    setEnabledModels(prev => {
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
      setEnabledModels(prev => {
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
    <div className="flex h-screen overflow-hidden bg-[#f7f7f6] text-neutral-950">
      <ModelSidebar
        models={models}
        enabledModels={enabledModels}
        onToggleModel={handleToggleModel}
        backendOnline={backendOnline}
      />
      <ControlDashboard
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
