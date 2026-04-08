export interface ChatMessage {
  id?: number;
  role: "user" | "assistant" | "system";
  content: string;
}

const OLLAMA_URL = "http://127.0.0.1:11434/api/chat";
const DEFAULT_MODEL = "gemma4:e2b";

export async function testConnection(): Promise<boolean> {
  try {
    const res = await fetch("http://127.0.0.1:11434/");
    return res.ok;
  } catch (e) {
    return false;
  }
}

export async function getModels(): Promise<string[]> {
  try {
    const res = await fetch("http://127.0.0.1:11434/api/tags");
    if (!res.ok) return [DEFAULT_MODEL];
    const data = await res.json();
    return data.models
      .map((m: any) => m.name)
      .filter((name: string) => !name.toLowerCase().includes("embed"));
  } catch (e) {
    return [DEFAULT_MODEL]; // Fallback to default if offline
  }
}


export async function* chatStream(messages: ChatMessage[], model: string = DEFAULT_MODEL) {
  // Format messages for Ollama payload
  const formattedMessages = messages.map(m => ({ role: m.role, content: m.content }));

  const response = await fetch(OLLAMA_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      model,
      messages: formattedMessages,
      stream: true,
    }),
  });

  if (!response.ok) {
    throw new Error(`Ollama Error: ${response.statusText}. Please ensure Ollama is running and has CORS configured if necessary.`);
  }

  const reader = response.body?.getReader();
  const decoder = new TextDecoder();

  if (!reader) throw new Error("No readable stream available.");

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      const chunk = decoder.decode(value, { stream: true });
      const lines = chunk.split("\n").filter(l => l.trim() !== "");
      
      for (const line of lines) {
        try {
          const parsed = JSON.parse(line);
          if (parsed.message?.content) {
            yield parsed.message.content;
          }
        } catch (e) {
          console.warn("Could not parse JSON chunk from Ollama", line);
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}
