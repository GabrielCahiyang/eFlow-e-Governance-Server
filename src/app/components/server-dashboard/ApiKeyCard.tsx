import { Check, Copy, Eye, EyeOff, KeyRound, Pencil, Save, Shuffle, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import { fetchAuthKey, generateRandomKey, updateAuthKey } from '../../services/authKeyService';
import { invalidateAuthKeyCache } from '../../services/llm';
import { DashboardPanel } from './DashboardPanel';

function masked(key: string) {
  if (!key) return 'No key loaded';
  if (key.length < 8) return '••••••••';
  return `${key.slice(0, 4)}${'•'.repeat(14)}${key.slice(-4)}`;
}

export function ApiKeyCard() {
  const [key, setKey] = useState('');
  const [draft, setDraft] = useState('');
  const [editing, setEditing] = useState(false);
  const [visible, setVisible] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    void fetchAuthKey().then((value) => {
      if (!value) return;
      setKey(value);
      setDraft(value);
    });
  }, []);

  const save = async () => {
    setSaving(true);
    const result = await updateAuthKey(draft);
    setSaving(false);
    if (!result.ok) {
      setMessage(result.error ?? 'The credential could not be updated.');
      return;
    }
    invalidateAuthKeyCache();
    setKey(draft);
    setEditing(false);
    setMessage('Credential saved to Supabase and activated immediately.');
  };

  const copy = async () => {
    if (!key) return;
    await navigator.clipboard.writeText(key);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1_800);
  };

  return (
    <DashboardPanel title="API credential" description="Private gateway-to-model authentication" action={<KeyRound className="h-4 w-4 text-neutral-400" />}>
      <div className="p-5">
        {editing ? (
          <input value={draft} onChange={(event) => setDraft(event.target.value)} className="h-10 w-full rounded-xl border border-neutral-300 bg-white px-3 font-mono text-xs text-neutral-900 outline-none ring-0 transition focus:border-neutral-950" aria-label="API credential" />
        ) : (
          <div className="flex items-center gap-2 rounded-xl border border-neutral-200 bg-neutral-50 p-2">
            <code className="min-w-0 flex-1 truncate px-2 text-xs text-neutral-700">{visible ? key || 'No key loaded' : masked(key)}</code>
            <button onClick={() => setVisible((current) => !current)} className="flex h-8 w-8 items-center justify-center rounded-lg border border-neutral-200 bg-white text-neutral-500 hover:text-neutral-900" title={visible ? 'Hide key' : 'Reveal key'}>{visible ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}</button>
            <button onClick={copy} disabled={!key} className="flex h-8 w-8 items-center justify-center rounded-lg border border-neutral-200 bg-white text-neutral-500 hover:text-neutral-900 disabled:opacity-40" title="Copy key">{copied ? <Check className="h-3.5 w-3.5 text-emerald-600" /> : <Copy className="h-3.5 w-3.5" />}</button>
          </div>
        )}

        <div className="mt-4 flex flex-wrap gap-2">
          <button onClick={() => { if (editing) { setDraft(key); setEditing(false); } else { setEditing(true); } }} className="inline-flex h-9 items-center gap-2 rounded-lg border border-neutral-200 bg-white px-3 text-xs font-semibold text-neutral-700 hover:bg-neutral-50">
            {editing ? <X className="h-3.5 w-3.5" /> : <Pencil className="h-3.5 w-3.5" />}{editing ? 'Cancel' : 'Edit'}
          </button>
          <button onClick={() => { setDraft(generateRandomKey(32)); setEditing(true); }} className="inline-flex h-9 items-center gap-2 rounded-lg border border-neutral-200 bg-white px-3 text-xs font-semibold text-neutral-700 hover:bg-neutral-50"><Shuffle className="h-3.5 w-3.5" />Generate secure key</button>
          {editing && <button onClick={save} disabled={saving || draft.length < 8} className="inline-flex h-9 items-center gap-2 rounded-lg bg-neutral-950 px-3 text-xs font-semibold text-white hover:bg-neutral-800 disabled:opacity-50"><Save className="h-3.5 w-3.5" />{saving ? 'Saving…' : 'Save to Supabase'}</button>}
        </div>
        <p className={`mb-0 mt-3 text-[11px] ${message?.includes('could not') ? 'text-red-600' : 'text-neutral-500'}`}>{message ?? 'Changing this key updates the private server credential; it is never published as the Cloudflare endpoint.'}</p>
      </div>
    </DashboardPanel>
  );
}
