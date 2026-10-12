// ── Server Log Streaming Service ─────────────────────────────────────
// Connects to GET /api/logs/stream via EventSource (SSE) and provides
// a React hook for consuming live logs.

import { useState, useEffect, useRef, useCallback } from "react";

const SSE_URL = "/api/logs/stream";

// ── Types ────────────────────────────────────────────────────────────

export type LogLevel = "INFO" | "WARNING" | "ERROR" | "DEBUG";

export type LogType =
  | "startup"
  | "shutdown"
  | "model_load"
  | "chat_request"
  | "auth"
  | "health"
  | "error"
  | "general";

export type LogEntry = {
  id?: string;
  timestamp: string;
  level: LogLevel;
  message: string;
  source: string;
  type: LogType;
  extra?: {
    model?: string;
    tokens?: number;
    latency_ms?: number;
    stream?: boolean;
  };
};

export type ServerStatus = "connecting" | "online" | "offline" | "error";

export type ModelStats = {
  requests: number;
  tokens: number;
  totalLatencyMs: number;
  avgLatencyMs: number;
  lastUsed: string; // ISO timestamp
};

export type UsageStats = {
  totalRequests: number;
  totalTokens: number;
  avgLatencyMs: number;
  modelUsage: Record<string, ModelStats>;
  // Extended fields
  serverStartTime: string | null;
  tokensPerSecond: number;
  peakLatencyMs: number;
  minLatencyMs: number;
  errorsCount: number;
  authFailures: number;
  totalGenerationTimeMs: number;
};

// ── Filter helpers ───────────────────────────────────────────────────

const HEALTH_TYPES: LogType[] = ["health"];

export function isHealthLog(entry: LogEntry): boolean {
  return HEALTH_TYPES.includes(entry.type);
}

export function isMeaningfulLog(entry: LogEntry): boolean {
  return !isHealthLog(entry);
}

// ── Log level color mapping ──────────────────────────────────────────

export function getLogColor(entry: LogEntry): string {
  if (entry.type === "error" || entry.level === "ERROR") return "#ef4444";
  if (entry.type === "auth" || entry.level === "WARNING") return "#f59e0b";
  if (entry.type === "chat_request") return "#60a5fa";
  if (entry.type === "model_load") return "#a78bfa";
  if (entry.type === "startup") return "#4ade80";
  if (entry.type === "shutdown") return "#f87171";
  if (entry.type === "health") return "rgba(255,255,255,0.25)";
  return "rgba(255,255,255,0.55)";
}

export function getLogTypeLabel(type: LogType): string {
  switch (type) {
    case "startup":
      return "STARTUP";
    case "shutdown":
      return "SHUTDOWN";
    case "model_load":
      return "MODEL";
    case "chat_request":
      return "CHAT";
    case "auth":
      return "AUTH";
    case "health":
      return "HEALTH";
    case "error":
      return "ERROR";
    default:
      return "LOG";
  }
}

// ── Hook: useServerLogs ──────────────────────────────────────────────

const MAX_LOGS = 500;

const INITIAL_STATS: UsageStats = {
  totalRequests: 0,
  totalTokens: 0,
  avgLatencyMs: 0,
  modelUsage: {},
  serverStartTime: null,
  tokensPerSecond: 0,
  peakLatencyMs: 0,
  minLatencyMs: Infinity,
  errorsCount: 0,
  authFailures: 0,
  totalGenerationTimeMs: 0,
};

export function useServerLogs(enabled: boolean = true) {
  const seen = useRef(new Set<string>());
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [serverStatus, setServerStatus] = useState<ServerStatus>("connecting");
  const [usageStats, setUsageStats] = useState<UsageStats>({
    ...INITIAL_STATS,
  });
  const eventSourceRef = useRef<EventSource | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const processEntry = useCallback((entry: LogEntry) => {
    const identity =
      entry.id ?? `${entry.timestamp}:${entry.source}:${entry.message}`;
    if (seen.current.has(identity)) return;
    seen.current.add(identity);
    if (seen.current.size > 2_000) {
      const oldest = seen.current.values();
      for (let i = 0; i < 500; i++) {
        const value = oldest.next().value;
        if (value) seen.current.delete(value);
      }
    }
    // Update logs
    setLogs((prev) => {
      const updated = [...prev, entry];
      return updated.length > MAX_LOGS ? updated.slice(-MAX_LOGS) : updated;
    });

    // Update server status from log content
    if (entry.type === "startup") {
      setServerStatus("online");
    } else if (entry.type === "shutdown") {
      setServerStatus("offline");
    }

    // Track startup time
    if (
      entry.type === "startup" &&
      entry.message.includes("Application startup complete")
    ) {
      setUsageStats((prev) => ({ ...prev, serverStartTime: entry.timestamp }));
    }

    // Track errors
    if (entry.type === "error") {
      setUsageStats((prev) => ({ ...prev, errorsCount: prev.errorsCount + 1 }));
    }

    // Track auth failures
    if (entry.type === "auth") {
      setUsageStats((prev) => ({
        ...prev,
        authFailures: prev.authFailures + 1,
      }));
    }

    // Track usage stats for chat requests
    if (entry.type === "chat_request" && entry.extra) {
      const { model, tokens = 0, latency_ms = 0 } = entry.extra;

      setUsageStats((prev) => {
        const newTotal = prev.totalRequests + 1;
        const newTokens = prev.totalTokens + tokens;
        const newTotalGenTime = prev.totalGenerationTimeMs + latency_ms;
        const newAvg = newTotalGenTime / newTotal;
        const newPeak = Math.max(prev.peakLatencyMs, latency_ms);
        const newMin = Math.min(
          prev.minLatencyMs === Infinity ? latency_ms : prev.minLatencyMs,
          latency_ms,
        );
        const newTps =
          newTotalGenTime > 0 ? (newTokens / newTotalGenTime) * 1000 : 0;

        // Per-model stats
        const newModelUsage = { ...prev.modelUsage };
        if (model) {
          const existing = newModelUsage[model] || {
            requests: 0,
            tokens: 0,
            totalLatencyMs: 0,
            avgLatencyMs: 0,
            lastUsed: "",
          };
          const updatedModel: ModelStats = {
            requests: existing.requests + 1,
            tokens: existing.tokens + tokens,
            totalLatencyMs: existing.totalLatencyMs + latency_ms,
            avgLatencyMs: Math.round(
              (existing.totalLatencyMs + latency_ms) / (existing.requests + 1),
            ),
            lastUsed: entry.timestamp,
          };
          newModelUsage[model] = updatedModel;
        }

        return {
          ...prev,
          totalRequests: newTotal,
          totalTokens: newTokens,
          avgLatencyMs: Math.round(newAvg),
          modelUsage: newModelUsage,
          totalGenerationTimeMs: newTotalGenTime,
          peakLatencyMs: newPeak,
          minLatencyMs: newMin,
          tokensPerSecond: Math.round(newTps * 10) / 10,
        };
      });
    }
  }, []);

  const connect = useCallback(() => {
    if (!enabled) return;
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    setServerStatus("connecting");
    const es = new EventSource(SSE_URL);
    eventSourceRef.current = es;

    es.onopen = () => {
      setServerStatus("online");
    };

    es.onmessage = (event) => {
      try {
        const entry: LogEntry = JSON.parse(event.data);
        processEntry(entry);
      } catch {
        // skip malformed
      }
    };

    es.onerror = () => {
      es.close();
      eventSourceRef.current = null;
      setServerStatus("offline");

      // Auto-reconnect after 5 seconds
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = setTimeout(() => {
        connect();
      }, 5000);
    };
  }, [enabled, processEntry]);

  useEffect(() => {
    connect();
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
        eventSourceRef.current = null;
      }
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
      }
    };
  }, [connect]);

  const clearLogs = useCallback(() => {
    setLogs([]);
  }, []);

  return {
    logs,
    serverStatus,
    usageStats,
    clearLogs,
  };
}
