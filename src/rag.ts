/**
 * RAG backend client — mirrors the FastAPI routes in backend/
 */

const RAG_URL = "http://localhost:8000";

export type FileStatus = "pending" | "processing" | "chunked" | "indexed" | "failed";

export interface RagFile {
  id: string;
  filename: string;
  size_bytes: number;
  size_human: string;
  context: string;
  status: FileStatus;
  total_chunks: number | null;
  error: string | null;
  created_at: string;
}

export interface StatusUpdate {
  status: FileStatus;
  total_chunks: number | null;
  error: string | null;
}

// ── Ingest ────────────────────────────────────────────────────────────────────

export async function uploadFile(
  file: File,
  context: "global" | string
): Promise<{ file_id: string; status: FileStatus }> {
  const form = new FormData();
  form.append("file", file);
  form.append("context", context);

  const res = await fetch(`${RAG_URL}/ingest/upload`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function deleteFile(fileId: string): Promise<void> {
  const res = await fetch(`${RAG_URL}/ingest/${fileId}`, { method: "DELETE" });
  if (!res.ok) throw new Error(await res.text());
}

// ── File listing ──────────────────────────────────────────────────────────────

export async function listFiles(context: string): Promise<RagFile[]> {
  const res = await fetch(`${RAG_URL}/files?context=${encodeURIComponent(context)}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getFile(fileId: string): Promise<RagFile> {
  const res = await fetch(`${RAG_URL}/files/${fileId}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

/**
 * Subscribe to live status updates for a file via SSE.
 * Calls onUpdate until the file reaches "indexed" or "failed".
 */
export function watchFileStatus(
  fileId: string,
  onUpdate: (update: StatusUpdate) => void,
  onDone?: () => void
): () => void {
  const es = new EventSource(`${RAG_URL}/files/${fileId}/stream`);

  es.onmessage = (e) => {
    const data: StatusUpdate = JSON.parse(e.data);
    onUpdate(data);
    if (data.status === "indexed" || data.status === "failed") {
      es.close();
      onDone?.();
    }
  };

  es.onerror = () => {
    es.close();
    onDone?.();
  };

  // Return cleanup function
  return () => es.close();
}

// ── RAG query ─────────────────────────────────────────────────────────────────

export interface ChatMessage {
  role: "user" | "assistant" | "system";
  content: string;
}

/**
 * RAG-augmented streaming chat.
 * Yields tokens. The first SSE event is "sources" with filenames used.
 */
export async function* ragChatStream(
  messages: ChatMessage[],
  model: string,
  sessionId?: string
): AsyncGenerator<{ type: "sources"; sources: string[] } | { type: "token"; token: string }> {
  const res = await fetch(`${RAG_URL}/query/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages, model, session_id: sessionId ?? null }),
  });

  if (!res.ok) throw new Error(await res.text());

  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    for (const line of lines) {
      if (line.startsWith("event: sources")) continue;
      if (line.startsWith("data: ")) {
        const raw = line.slice(6).trim();
        if (raw === "[DONE]") return;
        try {
          const parsed = JSON.parse(raw);
          if (Array.isArray(parsed)) {
            yield { type: "sources", sources: parsed };
          } else if (parsed.token) {
            yield { type: "token", token: parsed.token };
          }
        } catch {}
      }
    }
  }
}
