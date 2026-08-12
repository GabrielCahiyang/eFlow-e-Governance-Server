// ── Local LLM Backend API service ────────────────────────────────────
// All requests go through the Vite dev-server proxy (/api → localhost:8321)
// so there are no CORS issues in the browser.

const BASE = '/api';

let cachedAuthKey: string | null = null;
let authKeyPromise: Promise<string | null> | null = null;

export function invalidateAuthKeyCache(): void {
  cachedAuthKey = null;
  authKeyPromise = null;
}

async function getAuthKey(): Promise<string | null> {
  if (cachedAuthKey) return cachedAuthKey;
  if (!authKeyPromise) {
    authKeyPromise = fetch(`${BASE}/authkey`)
      .then(async (res) => {
        if (!res.ok) return null;
        const data = await res.json();
        const key = typeof data.api_key === 'string' ? data.api_key : null;
        if (key) cachedAuthKey = key;
        return key;
      })
      .catch(() => null)
      .finally(() => {
        authKeyPromise = null;
      });
  }
  return authKeyPromise;
}

async function withAuthHeaders(
  extra: Record<string, string> = {}
): Promise<Record<string, string>> {
  const key = await getAuthKey();
  return key ? { ...extra, Authorization: `Bearer ${key}` } : { ...extra };
}

// ── Types ────────────────────────────────────────────────────────────

export type LLMModel = {
  name: string;
  model: string;
  modified_at: string;
  size: number;
  digest: string;
  details: {
    parent_model: string;
    format: string;
    family: string;
    families: string[] | null;
    parameter_size: string;
    quantization_level: string;
  };
  downloaded?: boolean;
};

export type RunningModel = {
  name: string;
  model: string;
  size: number;
  size_vram: number;
  expires_at: string;
};

export type ChatMessage = {
  role: 'system' | 'user' | 'assistant';
  content: string;
  images?: string[]; // base64-encoded images for vision models
};

// ── List all available models (/api/tags) ────────────────────────────

export async function listModels(): Promise<LLMModel[]> {
  const res = await fetch(`${BASE}/tags`, {
    headers: await withAuthHeaders(),
  });
  if (!res.ok) throw new Error(`/api/tags failed: ${res.status}`);
  const data = await res.json();
  return data.models ?? [];
}

// ── List currently-loaded (running) models (/api/ps) ─────────────────

export async function listRunningModels(): Promise<RunningModel[]> {
  const res = await fetch(`${BASE}/ps`, {
    headers: await withAuthHeaders(),
  });
  if (!res.ok) throw new Error(`/api/ps failed: ${res.status}`);
  const data = await res.json();
  return data.models ?? [];
}

// ── Chat completion (non-streaming) ──────────────────────────────────

export async function chatCompletion(
  model: string,
  messages: ChatMessage[],
): Promise<{ content: string; totalDuration: number; evalCount: number }> {
  const res = await fetch(`${BASE}/chat`, {
    method: 'POST',
    headers: await withAuthHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ model, messages, stream: false }),
  });

  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`/api/chat failed (${res.status}): ${errText}`);
  }

  const data = await res.json();
  return {
    content: data.message?.content ?? '',
    totalDuration: data.total_duration ?? 0,   // nanoseconds
    evalCount: data.eval_count ?? 0,
  };
}

// ── Streaming chat completion ────────────────────────────────────────

export async function chatCompletionStream(
  model: string,
  messages: ChatMessage[],
  onToken: (token: string) => void,
  onDone: (stats: { totalDuration: number; evalCount: number }) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${BASE}/chat`, {
    method: 'POST',
    headers: await withAuthHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ model, messages, stream: true }),
    signal,
  });

  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`/api/chat failed (${res.status}): ${errText}`);
  }

  const reader = res.body?.getReader();
  if (!reader) throw new Error('No readable stream');

  const decoder = new TextDecoder();
  let buffer = '';
  let lastStats = { totalDuration: 0, evalCount: 0 };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    // Server sends newline-delimited JSON
    const lines = buffer.split('\n');
    buffer = lines.pop() ?? '';

    for (const line of lines) {
      if (!line.trim()) continue;
      try {
        const json = JSON.parse(line);
        if (json.message?.content) {
          onToken(json.message.content);
        }
        if (json.done) {
          lastStats = {
            totalDuration: json.total_duration ?? 0,
            evalCount: json.eval_count ?? 0,
          };
        }
      } catch {
        // skip malformed lines
      }
    }
  }

  onDone(lastStats);
}

// ── Check if the backend is reachable ────────────────────────────────

export async function pingBackend(): Promise<boolean> {
  try {
    const res = await fetch(`${BASE}/health`, { signal: AbortSignal.timeout(3000) });
    return res.ok;
  } catch {
    return false;
  }
}

// ── Trigger model download ───────────────────────────────────────────

export async function downloadModel(modelTag: string): Promise<boolean> {
  try {
    const res = await fetch(`${BASE}/download`, {
      method: 'POST',
      headers: await withAuthHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ model: modelTag }),
    });
    return res.ok;
  } catch {
    return false;
  }
}

// ── Toggle model enabled/disabled ────────────────────────────────────

export async function toggleModel(
  modelTag: string,
  enabled: boolean,
): Promise<{ ok: boolean; disabledModels: string[] }> {
  try {
    const res = await fetch(`${BASE}/models/toggle`, {
      method: 'PUT',
      headers: await withAuthHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ model: modelTag, enabled }),
    });
    if (!res.ok) return { ok: false, disabledModels: [] };
    const data = await res.json();
    return { ok: true, disabledModels: data.disabled_models ?? [] };
  } catch {
    return { ok: false, disabledModels: [] };
  }
}

// ── Get disabled models list ─────────────────────────────────────────

export async function getDisabledModels(): Promise<string[]> {
  try {
    const res = await fetch(`${BASE}/models/status`, {
      headers: await withAuthHeaders(),
    });
    if (!res.ok) return [];
    const data = await res.json();
    return data.disabled_models ?? [];
  } catch {
    return [];
  }
}
