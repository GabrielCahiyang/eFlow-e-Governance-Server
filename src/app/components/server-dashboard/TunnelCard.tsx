import { Check, Cloud, Copy, RefreshCw, ShieldCheck } from 'lucide-react';
import { useEffect, useState } from 'react';
import type { TunnelSnapshot } from '../../services/operationsService';
import { DashboardPanel } from './DashboardPanel';

function relativeTime(value: string | null) {
  if (!value) return 'No heartbeat received';
  const seconds = Math.max(0, Math.round((Date.now() - new Date(value).getTime()) / 1000));
  if (seconds < 60) return `Heartbeat ${seconds}s ago`;
  return `Heartbeat ${Math.round(seconds / 60)}m ago`;
}

type Props = {
  tunnel: TunnelSnapshot | null;
  rotating: boolean;
  onRotate: () => Promise<void>;
};

export function TunnelCard({ tunnel, rotating, onRotate }: Props) {
  const [copied, setCopied] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);

  useEffect(() => {
    if (tunnel?.status === 'online' && !rotating) setFeedback(null);
  }, [rotating, tunnel?.status]);

  const copyEndpoint = async () => {
    if (!tunnel?.endpoint) return;
    await navigator.clipboard.writeText(tunnel.endpoint);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1_800);
  };

  const rotate = async () => {
    if (!window.confirm('Generate a new Cloudflare Quick Tunnel URL? The current AI endpoint will briefly disconnect while every eFlow client is updated through Supabase.')) return;
    try {
      await onRotate();
      setFeedback('Rotation accepted. The supervisor is generating and publishing a fresh URL.');
    } catch {
      setFeedback('The rotation request could not be sent. Check the server logs.');
    }
  };

  const isOnline = tunnel?.status === 'online' && !rotating;
  return (
    <DashboardPanel
      title="Cloudflare connection"
      description="Automatically published to every eFlow client through Supabase"
      action={<span className={`rounded-full px-2.5 py-1 text-[10px] font-semibold ${isOnline ? 'bg-emerald-50 text-emerald-700' : rotating ? 'bg-amber-50 text-amber-700' : 'bg-red-50 text-red-700'}`}>{rotating ? 'Rotating' : isOnline ? 'Online' : tunnel?.status ?? 'Unknown'}</span>}
      className="lg:col-span-2"
    >
      <div className="grid gap-5 p-5 lg:grid-cols-[1fr_auto] lg:items-center">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-xs font-semibold text-neutral-900"><Cloud className="h-4 w-4 text-blue-600" />Current public AI endpoint</div>
          <div className="mt-3 flex min-w-0 items-center gap-2 rounded-xl border border-neutral-200 bg-neutral-50 p-2">
            <code className="min-w-0 flex-1 truncate px-2 text-xs text-neutral-700" title={tunnel?.endpoint ?? undefined}>{tunnel?.endpoint ?? 'Waiting for the tunnel supervisor to publish an endpoint…'}</code>
            <button type="button" onClick={copyEndpoint} disabled={!tunnel?.endpoint} className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-neutral-200 bg-white text-neutral-500 transition hover:text-neutral-900 disabled:opacity-40" title="Copy endpoint">
              {copied ? <Check className="h-3.5 w-3.5 text-emerald-600" /> : <Copy className="h-3.5 w-3.5" />}
            </button>
          </div>
          <div className="mt-3 flex flex-wrap gap-x-5 gap-y-2 text-[11px] text-neutral-500">
            <span className="flex items-center gap-1.5"><ShieldCheck className="h-3.5 w-3.5 text-emerald-600" />Endpoint discovery is automatic</span>
            <span>{relativeTime(tunnel?.heartbeat ?? null)}</span>
          </div>
          {(feedback || tunnel?.message) && <p className="mb-0 mt-3 text-xs leading-5 text-neutral-500">{feedback ?? tunnel?.message}</p>}
        </div>
        <button type="button" onClick={rotate} disabled={rotating} className="inline-flex h-10 items-center justify-center gap-2 rounded-xl bg-neutral-950 px-4 text-xs font-semibold text-white transition hover:bg-neutral-800 disabled:cursor-wait disabled:opacity-60">
          <RefreshCw className={`h-4 w-4 ${rotating ? 'animate-spin' : ''}`} />
          {rotating ? 'Generating new link…' : 'Rotate endpoint'}
        </button>
      </div>
    </DashboardPanel>
  );
}
