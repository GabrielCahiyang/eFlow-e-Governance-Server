import { Button } from "@vibe/button";
import { TextField } from "@vibe/text-inputs";
import { Check, Copy, Eye, EyeOff, Pencil, Save, Shuffle } from "lucide-react";
import { useEffect, useState } from "react";
import {
  fetchAuthKey,
  generateRandomKey,
  updateAuthKey,
} from "../../services/authKeyService";
import { invalidateAuthKeyCache } from "../../services/llm";

export function ApiKeyCard() {
  const [key, setKey] = useState("");
  const [draft, setDraft] = useState("");
  const [editing, setEditing] = useState(false);
  const [visible, setVisible] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    let active = true;
    void fetchAuthKey().then((value) => {
      if (active && value) {
        setKey(value);
        setDraft(value);
      }
    });
    return () => {
      active = false;
    };
  }, []);
  const save = async () => {
    setSaving(true);
    try {
      const result = await updateAuthKey(draft);
      if (!result.ok) {
        setMessage(result.error ?? "Could not save the credential.");
        return;
      }
      invalidateAuthKeyCache();
      setKey(draft);
      setEditing(false);
      setVisible(false);
      setMessage("Credential updated.");
    } finally {
      setSaving(false);
    }
  };
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(key);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      setMessage("Could not copy the credential.");
    }
  };
  return (
    <section className="panel">
      <div className="panel-header">
        <h2>API credential</h2>
      </div>
      <div className="panel-body">
        <label className="field-label" htmlFor="server-api-key">
          Private server key
        </label>
        {editing ? (
          <TextField
            id="server-api-key"
            value={draft}
            onChange={setDraft}
            autoComplete="off"
            placeholder="Enter a private key"
            inputAriaLabel="Private server key"
          />
        ) : (
          <div className="field-box">
            <code>
              {key
                ? visible
                  ? key
                  : "••••••••••••••••••••••••"
                : "No credential received"}
            </code>
            <Button
              kind="tertiary"
              size="small"
              onClick={() => setVisible((v) => !v)}
              disabled={!key}
              aria-label={visible ? "Hide credential" : "Reveal credential"}
            >
              {visible ? <EyeOff size={16} /> : <Eye size={16} />}
            </Button>
            <Button
              kind="tertiary"
              size="small"
              onClick={() => void copy()}
              disabled={!key}
              aria-label="Copy credential"
            >
              {copied ? <Check size={16} /> : <Copy size={16} />}
            </Button>
          </div>
        )}
        <div className="field-actions">
          <Button
            kind="secondary"
            size="small"
            leftIcon={({ className }) => (
              <Pencil className={className} size={16} />
            )}
            onClick={() => {
              setDraft(key);
              setEditing((v) => !v);
            }}
          >
            {editing ? "Cancel" : "Edit key"}
          </Button>
          <Button
            kind="tertiary"
            size="small"
            leftIcon={({ className }) => (
              <Shuffle className={className} size={16} />
            )}
            onClick={() => {
              setDraft(generateRandomKey(32));
              setEditing(true);
            }}
          >
            Generate key
          </Button>
          {editing && (
            <Button
              size="small"
              leftIcon={({ className }) => (
                <Save className={className} size={16} />
              )}
              onClick={() => void save()}
              loading={saving}
              disabled={draft.length < 8}
            >
              Save key
            </Button>
          )}
        </div>
        {message && (
          <p className="feedback" role="status">
            {message}
          </p>
        )}
        <p className="field-help">
          Used by the gateway to authenticate with this server. This credential
          is separate from the public endpoint.
        </p>
      </div>
    </section>
  );
}
