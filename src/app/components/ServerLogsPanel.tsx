import { useEffect, useRef, useState } from 'react';
import { Terminal, Trash2 } from 'lucide-react';
import type { LogEntry, ServerStatus, UsageStats } from '../services/serverLogs';
import { getLogColor, getLogTypeLabel, isMeaningfulLog } from '../services/serverLogs';

type Props = {
  logs: LogEntry[];
  serverStatus: ServerStatus;
  usageStats: UsageStats;
  onClear: () => void;
};

function formatTimestamp(value: string) {
  return new Date(value).toLocaleTimeString('en-US', {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

export function ServerLogsPanel({ logs, serverStatus, usageStats, onClear }: Props) {
  const [showHealth, setShowHealth] = useState(false);
  const [autoScroll, setAutoScroll] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);
  const visibleLogs = showHealth ? logs : logs.filter(isMeaningfulLog);

  useEffect(() => {
    if (autoScroll && scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [autoScroll, visibleLogs.length]);

  return (
    <div className="flex h-full flex-col bg-[#111310] text-neutral-200">
      <div className="flex flex-wrap items-center gap-3 border-b border-white/10 px-4 py-2.5">
        <span className="flex items-center gap-2 text-[11px] font-semibold text-neutral-300"><span className={`h-2 w-2 rounded-full ${serverStatus === 'online' ? 'bg-emerald-400' : 'bg-red-400'}`} />{serverStatus === 'online' ? 'Streaming' : 'Disconnected'}</span>
        <span className="text-[10px] text-neutral-500">{visibleLogs.length} events</span>
        <span className="text-[10px] text-neutral-500">{usageStats.totalRequests} AI requests</span>

        <label className="ml-auto flex cursor-pointer items-center gap-2 text-[10px] text-neutral-400"><input type="checkbox" checked={showHealth} onChange={(event) => setShowHealth(event.target.checked)} className="accent-emerald-500" />Health polls</label>
        <label className="flex cursor-pointer items-center gap-2 text-[10px] text-neutral-400"><input type="checkbox" checked={autoScroll} onChange={(event) => setAutoScroll(event.target.checked)} className="accent-emerald-500" />Follow</label>
        <button onClick={onClear} className="flex h-7 w-7 items-center justify-center rounded-md border border-white/10 bg-white/5 text-neutral-400 hover:bg-white/10 hover:text-white" title="Clear buffered logs"><Trash2 className="h-3.5 w-3.5" /></button>
      </div>

      <div ref={scrollRef} className="flex-1 overflow-y-auto px-3 py-2 font-mono text-[10px] leading-5">
        {visibleLogs.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-neutral-600"><Terminal className="h-6 w-6" /><span>Waiting for server activity…</span></div>
        ) : visibleLogs.map((entry, index) => {
          const color = getLogColor(entry);
          return (
            <div key={`${entry.timestamp}-${index}`} className="grid grid-cols-[64px_58px_1fr_auto] items-start gap-2 rounded px-2 py-0.5 hover:bg-white/[0.04]">
              <span className="text-neutral-600">{formatTimestamp(entry.timestamp)}</span>
              <span className="truncate text-[9px] font-semibold uppercase tracking-[0.06em]" style={{ color }}>{getLogTypeLabel(entry.type)}</span>
              <span className="min-w-0 break-words text-neutral-300">{entry.message}</span>
              <span className="flex gap-2 text-neutral-500">{entry.extra?.tokens != null && <span>{entry.extra.tokens}tk</span>}{entry.extra?.latency_ms != null && <span>{entry.extra.latency_ms}ms</span>}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
