import { Button } from "@vibe/button";
import { Check, Copy, RefreshCw } from "lucide-react";
import { useState } from "react";
import type { TunnelSnapshot } from "../../services/operationsService";

export function TunnelCard({
  tunnel,
  rotating,
  onRotate,
}: {
  tunnel: TunnelSnapshot | null;
  rotating: boolean;
  onRotate: () => Promise<void>;
}) {
  const [copied, setCopied] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);
  const copy = async () => {
    if (!tunnel?.endpoint) return;
    try {
      await navigator.clipboard.writeText(tunnel.endpoint);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      setFeedback("Could not copy the endpoint.");
    }
  };
  const rotate = async () => {
    if (
      !window.confirm(
        "Rotate the public AI endpoint? Active connections may briefly disconnect while the new endpoint is published.",
      )
    )
      return;
    try {
      await onRotate();
      setFeedback("Endpoint rotation requested.");
    } catch {
      setFeedback("Could not rotate the endpoint. Check the activity log.");
    }
  };
  const seconds = tunnel?.heartbeat
    ? Math.max(
        0,
        Math.round((Date.now() - new Date(tunnel.heartbeat).getTime()) / 1000),
      )
    : null;
  return (
    <section className="panel">
      <div className="panel-header">
        <h2>Public connection</h2>
        <span className="status-text">
          <i
            className={`status-dot ${tunnel?.status === "online" && !rotating ? "positive" : ""}`}
          />
          {rotating ? "Rotating" : (tunnel?.status ?? "Unavailable")}
        </span>
      </div>
      <div className="panel-body">
        <span className="field-label">AI endpoint</span>
        <div className="field-box">
          <code title={tunnel?.endpoint ?? undefined}>
            {tunnel?.endpoint ?? "No endpoint received"}
          </code>
          <Button
            kind="tertiary"
            size="small"
            onClick={() => void copy()}
            disabled={!tunnel?.endpoint}
            aria-label="Copy endpoint"
          >
            {copied ? <Check size={16} /> : <Copy size={16} />}
          </Button>
        </div>
        <div style={{ marginTop: 18 }}>
          <div className="metric-line">
            <span>Connection</span>
            <strong>Cloudflare Quick Tunnel</strong>
          </div>
          <div className="metric-line">
            <span>Last heartbeat</span>
            <strong>
              {seconds == null
                ? "Not received"
                : seconds < 60
                  ? `${seconds}s ago`
                  : `${Math.round(seconds / 60)}m ago`}
            </strong>
          </div>
        </div>
        <div className="field-actions">
          <Button
            kind="secondary"
            size="small"
            leftIcon={({ className }) => (
              <RefreshCw className={className} size={16} />
            )}
            onClick={() => void rotate()}
            loading={rotating}
            disabled={!tunnel}
          >
            Rotate endpoint
          </Button>
        </div>
        {feedback && (
          <p className="feedback" role="status">
            {feedback}
          </p>
        )}
        <p className="field-help">
          The supervisor publishes new endpoints automatically. Rotate the
          endpoint only when you need a new connection.
        </p>
      </div>
    </section>
  );
}
