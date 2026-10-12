import { useEffect, useRef, useState } from "react";
import { Button } from "@vibe/button";
import { Terminal, Trash2 } from "lucide-react";
import type {
  LogEntry,
  ServerStatus,
  UsageStats,
} from "../services/serverLogs";
import { isMeaningfulLog } from "../services/serverLogs";

function serviceOf(entry: LogEntry) {
  const source = `${entry.source} ${entry.message}`.toLowerCase();
  if (/pygad|optimization/.test(source)) return "pygad";
  if (/polygon|blockchain|anchor_genesis|anchor_milestone/.test(source))
    return "blockchain";
  if (/laya/.test(source)) return "laya";
  if (
    /inference|model_runtime|proposal.pipeline|workspace.decomposition/.test(
      source,
    ) ||
    entry.type === "chat_request" ||
    entry.type === "model_load"
  )
    return "ai";
  return "server";
}
const labels: Record<string, string> = {
  pygad: "PyGAD",
  laya: "LAYA",
  blockchain: "Blockchain",
  ai: "AI",
  server: "Server",
};

export function ServerLogsPanel({
  logs,
  serverStatus,
  usageStats,
  onClear,
}: {
  logs: LogEntry[];
  serverStatus: ServerStatus;
  usageStats: UsageStats;
  onClear: () => void;
}) {
  const [showHealth, setShowHealth] = useState(false);
  const [autoScroll, setAutoScroll] = useState(true);
  const [service, setService] = useState("all");
  const scroll = useRef<HTMLDivElement>(null);
  const visible = (showHealth ? logs : logs.filter(isMeaningfulLog)).filter(
    (entry) => service === "all" || serviceOf(entry) === service,
  );
  useEffect(() => {
    if (autoScroll && scroll.current)
      scroll.current.scrollTop = scroll.current.scrollHeight;
  }, [autoScroll, visible.length]);
  return (
    <div className="activity-panel">
      <div className="activity-toolbar">
        <span className="status-text">
          <i
            className={`status-dot ${serverStatus === "online" ? "positive" : ""}`}
          />
          {serverStatus === "online" ? "Live" : "Not connected"}
        </span>
        <span className="subtle">{visible.length} events</span>
        <label className="service-filter">
          Service
          <select
            aria-label="Activity service filter"
            value={service}
            onChange={(event) => setService(event.target.value)}
          >
            <option value="all">All services</option>
            {Object.entries(labels).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          <input
            type="checkbox"
            checked={showHealth}
            onChange={(e) => setShowHealth(e.target.checked)}
          />
          Include health checks
        </label>
        <label>
          <input
            type="checkbox"
            checked={autoScroll}
            onChange={(e) => setAutoScroll(e.target.checked)}
          />
          Follow latest
        </label>
        <Button
          kind="tertiary"
          size="small"
          leftIcon={({ className }) => (
            <Trash2 className={className} size={16} />
          )}
          onClick={onClear}
        >
          Clear view
        </Button>
      </div>
      <div className="activity-rows" ref={scroll}>
        {visible.length ? (
          visible.map((entry, index) => (
            <div
              className={`activity-row ${entry.level === "ERROR" ? "is-error" : ""}`}
              key={entry.id ?? `${entry.timestamp}-${index}`}
            >
              <time dateTime={entry.timestamp}>
                {new Date(entry.timestamp).toLocaleTimeString([], {
                  hour12: false,
                  hour: "2-digit",
                  minute: "2-digit",
                  second: "2-digit",
                })}
              </time>
              <span className="activity-source">
                {entry.type === "chat_request"
                  ? "AI request"
                  : entry.type === "model_load"
                    ? "Model"
                    : entry.level === "ERROR"
                      ? "Error"
                      : labels[serviceOf(entry)]}
              </span>
              <span className="activity-message">{entry.message}</span>
              <span className="activity-latency">
                {entry.extra?.latency_ms != null
                  ? `${entry.extra.latency_ms} ms`
                  : ""}
              </span>
            </div>
          ))
        ) : (
          <div className="empty-state">
            <Terminal size={26} strokeWidth={1.3} />
            <h3>
              {service === "all" ? "No activity yet" : "No matching activity"}
            </h3>
            <p>Service events will appear here when they run.</p>
          </div>
        )}
      </div>
      <div className="queue-foot">
        <span>{usageStats.totalRequests} AI requests observed</span>
        <span>Latest 500 events</span>
      </div>
    </div>
  );
}
