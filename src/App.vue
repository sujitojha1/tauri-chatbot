<script setup lang="ts">
import { ref, onMounted, watch, nextTick, computed, onUnmounted } from "vue";
import { chatStream, getModels, type ChatMessage } from "./ollama";
import {
  uploadFile,
  deleteFile,
  listFiles,
  watchFileStatus,
  ragChatStream,
  type RagFile,
  type FileStatus,
} from "./rag";
import { marked } from "marked";

// ── Model selection ────────────────────────────────────────────────────────────
const MODEL_STORE_KEY = "local-ai-model-choice";
const availableModels = ref<string[]>([]);
const selectedModel = ref<string>("gemma4:e2b");

// ── Chat state ─────────────────────────────────────────────────────────────────
const message = ref("");
const isLoading = ref(false);
const chatHistory = ref<ChatMessage[]>([]);
const chatContainer = ref<HTMLElement | null>(null);
const lastSources = ref<string[]>([]);

// ── RAG backend availability ───────────────────────────────────────────────────
const ragAvailable = ref(false);

async function checkRagBackend() {
  try {
    const res = await fetch("http://localhost:8000/health");
    ragAvailable.value = res.ok;
  } catch {
    ragAvailable.value = false;
  }
}

// ── Session ID (per app launch) ────────────────────────────────────────────────
const sessionId = `session:${Date.now()}`;

// ── Global files (left panel) ──────────────────────────────────────────────────
const globalFiles = ref<RagFile[]>([]);
const globalUploading = ref(false);
const globalFileInput = ref<HTMLInputElement | null>(null);
// cleanup fns for SSE watchers keyed by file_id
const watchers: Record<string, () => void> = {};

async function refreshGlobalFiles() {
  if (!ragAvailable.value) return;
  globalFiles.value = await listFiles("global");
}

function startWatcher(file: RagFile) {
  if (watchers[file.id]) return;
  watchers[file.id] = watchFileStatus(
    file.id,
    (update) => {
      const idx = globalFiles.value.findIndex((f) => f.id === file.id);
      if (idx !== -1) {
        globalFiles.value[idx] = {
          ...globalFiles.value[idx],
          status: update.status,
          total_chunks: update.total_chunks,
          error: update.error,
        };
      }
    },
    () => {
      delete watchers[file.id];
      refreshGlobalFiles(); // sync size_human etc.
    }
  );
}

async function handleGlobalUpload(event: Event) {
  const files = (event.target as HTMLInputElement).files;
  if (!files?.length) return;

  globalUploading.value = true;
  for (const file of Array.from(files)) {
    try {
      const result = await uploadFile(file, "global");
      await refreshGlobalFiles();
      const record = globalFiles.value.find((f) => f.id === result.file_id);
      if (record) startWatcher(record);
    } catch (e: any) {
      console.error("Upload failed:", e.message);
    }
  }
  globalUploading.value = false;
  if (globalFileInput.value) globalFileInput.value.value = "";
}

async function handleDeleteGlobal(file: RagFile) {
  watchers[file.id]?.();
  delete watchers[file.id];
  await deleteFile(file.id);
  globalFiles.value = globalFiles.value.filter((f) => f.id !== file.id);
}

// ── Session files (chat header) ────────────────────────────────────────────────
const sessionFiles = ref<RagFile[]>([]);
const sessionUploading = ref(false);
const sessionFileInput = ref<HTMLInputElement | null>(null);

async function refreshSessionFiles() {
  if (!ragAvailable.value) return;
  sessionFiles.value = await listFiles(sessionId);
}

async function handleSessionUpload(event: Event) {
  const files = (event.target as HTMLInputElement).files;
  if (!files?.length) return;

  sessionUploading.value = true;
  for (const file of Array.from(files)) {
    try {
      const result = await uploadFile(file, sessionId);
      await refreshSessionFiles();
      const record = sessionFiles.value.find((f) => f.id === result.file_id);
      if (record) {
        watchers[record.id] = watchFileStatus(
          record.id,
          (update) => {
            const idx = sessionFiles.value.findIndex((f) => f.id === record.id);
            if (idx !== -1) {
              sessionFiles.value[idx] = {
                ...sessionFiles.value[idx],
                status: update.status,
                total_chunks: update.total_chunks,
                error: update.error,
              };
            }
          },
          () => {
            delete watchers[record.id];
            refreshSessionFiles();
          }
        );
      }
    } catch (e: any) {
      console.error("Session upload failed:", e.message);
    }
  }
  sessionUploading.value = false;
  if (sessionFileInput.value) sessionFileInput.value.value = "";
}

async function handleDeleteSession(file: RagFile) {
  watchers[file.id]?.();
  delete watchers[file.id];
  await deleteFile(file.id);
  sessionFiles.value = sessionFiles.value.filter((f) => f.id !== file.id);
}

// ── Status helpers ─────────────────────────────────────────────────────────────
function statusColor(s: FileStatus): string {
  return (
    {
      pending: "text-neutral-400",
      processing: "text-amber-500",
      chunked: "text-blue-500",
      indexed: "text-emerald-500",
      failed: "text-red-500",
    }[s] ?? "text-neutral-400"
  );
}

function statusDot(s: FileStatus): string {
  return (
    {
      pending: "bg-neutral-300",
      processing: "bg-amber-400 animate-pulse",
      chunked: "bg-blue-400 animate-pulse",
      indexed: "bg-emerald-400",
      failed: "bg-red-400",
    }[s] ?? "bg-neutral-300"
  );
}

function statusLabel(f: RagFile): string {
  if (f.status === "indexed") return `${f.total_chunks} chunks`;
  if (f.status === "chunked") return `chunking…`;
  if (f.status === "processing") return "parsing…";
  if (f.status === "failed") return "failed";
  return "pending";
}

const hasIndexedFiles = computed(
  () =>
    globalFiles.value.some((f) => f.status === "indexed") ||
    sessionFiles.value.some((f) => f.status === "indexed")
);

// ── Chat ───────────────────────────────────────────────────────────────────────
const scrollToBottom = () => {
  nextTick(() => {
    if (chatContainer.value) {
      chatContainer.value.scrollTop = chatContainer.value.scrollHeight;
    }
  });
};

const sendMessage = async () => {
  if (!message.value.trim() || isLoading.value) return;

  const userMsg = message.value.trim();
  message.value = "";
  lastSources.value = [];
  chatHistory.value.push({ id: Date.now(), role: "user", content: userMsg });

  const assistantId = Date.now() + 1;
  chatHistory.value.push({ id: assistantId, role: "assistant", content: "" });
  isLoading.value = true;

  try {
    if (ragAvailable.value && hasIndexedFiles.value) {
      // RAG-augmented path
      const stream = ragChatStream(
        chatHistory.value.slice(0, -1).map(({ role, content }) => ({ role, content })),
        selectedModel.value,
        sessionId
      );
      for await (const event of stream) {
        if (event.type === "sources") {
          lastSources.value = event.sources;
        } else {
          const idx = chatHistory.value.findIndex((m) => m.id === assistantId);
          if (idx !== -1) chatHistory.value[idx].content += event.token;
        }
      }
    } else {
      // Direct Ollama path (no RAG)
      const stream = chatStream(chatHistory.value.slice(0, -1), selectedModel.value);
      for await (const chunk of stream) {
        const idx = chatHistory.value.findIndex((m) => m.id === assistantId);
        if (idx !== -1) chatHistory.value[idx].content += chunk;
      }
    }
  } catch (err: any) {
    const idx = chatHistory.value.findIndex((m) => m.id === assistantId);
    if (idx !== -1) chatHistory.value[idx].content += `\n**Error:** ${err.message}`;
  } finally {
    isLoading.value = false;
  }
};

// ── Lifecycle ──────────────────────────────────────────────────────────────────
onMounted(async () => {
  chatHistory.value = [
    {
      id: Date.now(),
      role: "assistant",
      content:
        "Hello! I am your local PD Checker assistant. How can I help you today?",
    },
  ];
  scrollToBottom();

  const savedModel = localStorage.getItem(MODEL_STORE_KEY);
  if (savedModel) selectedModel.value = savedModel;

  getModels().then((models) => {
    availableModels.value = models;
    if (!models.includes(selectedModel.value) && models.length > 0) {
      selectedModel.value = models[0];
    }
  });

  await checkRagBackend();
  if (ragAvailable.value) {
    await refreshGlobalFiles();
    // Resume watchers for any in-progress files from a previous session
    globalFiles.value
      .filter((f) => !["indexed", "failed"].includes(f.status))
      .forEach((f) => startWatcher(f));
  }
});

onUnmounted(() => {
  Object.values(watchers).forEach((fn) => fn());
});

watch(selectedModel, (v) => localStorage.setItem(MODEL_STORE_KEY, v));
watch(chatHistory, scrollToBottom, { deep: true });
</script>

<template>
  <div class="flex h-screen w-screen overflow-hidden bg-neutral-50 text-neutral-900">

    <!-- ── Left Sidebar: Global Knowledge Base ─────────────────────────────── -->
    <aside class="w-64 border-r border-neutral-200 bg-white shadow-sm hidden md:flex flex-col shrink-0 z-20">
      <!-- Header -->
      <div class="p-4 border-b border-neutral-100 bg-white/70 backdrop-blur-md">
        <h2 class="font-semibold text-neutral-800 tracking-wide text-sm flex items-center gap-2">
          <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none"
            stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
            class="text-neutral-500">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <polyline points="14 2 14 8 20 8" />
            <line x1="16" y1="13" x2="8" y2="13" />
            <line x1="16" y1="17" x2="8" y2="17" />
          </svg>
          Knowledge Base
        </h2>
        <!-- RAG backend status -->
        <div class="mt-1.5 flex items-center gap-1.5">
          <span class="w-1.5 h-1.5 rounded-full" :class="ragAvailable ? 'bg-emerald-400' : 'bg-neutral-300'"></span>
          <span class="text-xs" :class="ragAvailable ? 'text-emerald-600' : 'text-neutral-400'">
            {{ ragAvailable ? 'RAG backend online' : 'RAG backend offline' }}
          </span>
        </div>
      </div>

      <!-- File list -->
      <div class="flex-1 overflow-y-auto p-3 space-y-2">
        <template v-if="!ragAvailable">
          <p class="text-xs text-neutral-400 text-center mt-6 px-2 leading-relaxed">
            Start the RAG backend to enable document ingestion.<br>
            <code class="text-[10px] bg-neutral-100 px-1 py-0.5 rounded">cd backend && ./start.sh</code>
          </p>
        </template>

        <template v-else-if="globalFiles.length === 0">
          <p class="text-xs text-neutral-400 text-center mt-6">No files ingested yet.</p>
        </template>

        <div
          v-for="file in globalFiles"
          :key="file.id"
          class="group relative bg-neutral-50 border border-neutral-200 rounded-lg p-2.5 hover:border-neutral-300 transition-colors"
        >
          <!-- Filename -->
          <div class="flex items-start justify-between gap-1">
            <span class="text-xs font-medium text-neutral-700 truncate flex-1" :title="file.filename">
              {{ file.filename }}
            </span>
            <!-- Delete -->
            <button
              @click="handleDeleteGlobal(file)"
              class="opacity-0 group-hover:opacity-100 transition-opacity text-neutral-400 hover:text-red-500 shrink-0 mt-0.5"
              title="Remove file"
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none"
                stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          </div>

          <!-- Meta row: size + status -->
          <div class="mt-1.5 flex items-center justify-between gap-2">
            <span class="text-[10px] text-neutral-400">{{ file.size_human }}</span>
            <div class="flex items-center gap-1">
              <span class="w-1.5 h-1.5 rounded-full shrink-0" :class="statusDot(file.status)"></span>
              <span class="text-[10px]" :class="statusColor(file.status)">{{ statusLabel(file) }}</span>
            </div>
          </div>

          <!-- Progress bar while processing -->
          <div v-if="['pending','processing','chunked'].includes(file.status)"
            class="mt-1.5 h-0.5 bg-neutral-200 rounded-full overflow-hidden">
            <div class="h-full bg-amber-400 animate-pulse rounded-full w-3/4"></div>
          </div>

          <!-- Error tooltip -->
          <p v-if="file.error" class="mt-1 text-[10px] text-red-500 truncate" :title="file.error">
            {{ file.error }}
          </p>
        </div>
      </div>

      <!-- Upload button -->
      <div class="p-4 border-t border-neutral-100 bg-white/50 backdrop-blur-sm">
        <label
          class="text-sm px-4 py-2 w-full rounded-md border shadow-sm flex items-center justify-center gap-2 transition-colors"
          :class="ragAvailable && !globalUploading
            ? 'cursor-pointer bg-white border-neutral-200 text-neutral-700 hover:bg-neutral-50 hover:border-neutral-300'
            : 'cursor-not-allowed bg-neutral-100 border-neutral-200 text-neutral-400 opacity-60'"
        >
          <!-- spinner or icon -->
          <svg v-if="globalUploading" xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24"
            fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
            class="animate-spin">
            <path d="M21 12a9 9 0 1 1-6.219-8.56" />
          </svg>
          <svg v-else xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none"
            stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="17 8 12 3 7 8" />
            <line x1="12" y1="3" x2="12" y2="15" />
          </svg>
          <span class="font-medium text-xs">
            {{ globalUploading ? 'Uploading…' : 'Ingest File' }}
          </span>
          <input
            ref="globalFileInput"
            type="file"
            class="hidden"
            multiple
            accept=".pdf,.docx,.txt,.md,.html,.pptx,.xlsx"
            :disabled="!ragAvailable || globalUploading"
            @change="handleGlobalUpload"
          />
        </label>
      </div>
    </aside>

    <!-- ── Main Chat Area ───────────────────────────────────────────────────── -->
    <main class="flex flex-1 flex-col h-full overflow-hidden relative">

      <!-- Header -->
      <header class="flex items-center justify-between p-4 border-b border-neutral-200 bg-white/70 backdrop-blur-md z-10 w-full shadow-sm gap-3">
        <div class="flex items-center gap-3 min-w-0">
          <div
            class="w-3 h-3 rounded-full animate-pulse shadow-sm shrink-0"
            :class="isLoading ? 'bg-amber-500 shadow-amber-500/30' : 'bg-emerald-500 shadow-emerald-500/30'"
          ></div>
          <h1 class="font-semibold tracking-wide text-lg text-neutral-800 font-mono truncate">
            {{ selectedModel }}
          </h1>
          <!-- RAG mode pill -->
          <span v-if="ragAvailable && hasIndexedFiles"
            class="hidden sm:inline-flex items-center gap-1 text-[10px] font-medium px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-600 border border-emerald-200 shrink-0">
            <span class="w-1.5 h-1.5 bg-emerald-400 rounded-full"></span>RAG
          </span>
        </div>

        <div class="flex items-center gap-2 shrink-0">
          <!-- Session file upload -->
          <div v-if="ragAvailable" class="flex items-center gap-1.5">
            <!-- Session file chips -->
            <div v-for="f in sessionFiles" :key="f.id"
              class="hidden sm:flex items-center gap-1 text-[10px] px-2 py-1 rounded-full border bg-white"
              :class="f.status === 'indexed' ? 'border-emerald-200 text-emerald-600' : 'border-neutral-200 text-neutral-500'"
            >
              <span class="w-1.5 h-1.5 rounded-full shrink-0" :class="statusDot(f.status)"></span>
              <span class="truncate max-w-[80px]" :title="f.filename">{{ f.filename }}</span>
              <button @click="handleDeleteSession(f)" class="ml-0.5 text-neutral-400 hover:text-red-400">
                <svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 24 24" fill="none"
                  stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
                  <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
                </svg>
              </button>
            </div>

            <!-- Session upload button -->
            <label
              class="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-md border shadow-sm transition-colors"
              :class="!sessionUploading
                ? 'cursor-pointer bg-white border-neutral-200 text-neutral-600 hover:bg-neutral-50'
                : 'cursor-not-allowed bg-neutral-100 border-neutral-200 text-neutral-400 opacity-60'"
              title="Upload file for this session only"
            >
              <svg v-if="sessionUploading" xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24"
                fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
                class="animate-spin"><path d="M21 12a9 9 0 1 1-6.219-8.56" /></svg>
              <svg v-else xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none"
                stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="17 8 12 3 7 8" />
                <line x1="12" y1="3" x2="12" y2="15" />
              </svg>
              <span class="hidden sm:inline">{{ sessionUploading ? 'Uploading…' : 'Session file' }}</span>
              <input
                ref="sessionFileInput"
                type="file"
                class="hidden"
                multiple
                accept=".pdf,.docx,.txt,.md,.html,.pptx,.xlsx"
                :disabled="sessionUploading"
                @change="handleSessionUpload"
              />
            </label>
          </div>

          <!-- Model selector -->
          <select
            v-model="selectedModel"
            class="text-sm px-3 py-1.5 rounded-md bg-white border border-neutral-200 text-neutral-700 hover:bg-neutral-50 transition-colors focus:outline-none focus:ring-2 focus:ring-primary/20 appearance-none cursor-pointer pr-8 shadow-sm"
            style="background-image: url('data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%2216%22 height=%2216%22 viewBox=%220 0 24 24%22 fill=%22none%22 stroke=%22%234b5563%22 stroke-width=%222%22 stroke-linecap=%22round%22 stroke-linejoin=%22round%22><polyline points=%226 9 12 15 18 9%22></polyline></svg>'); background-repeat: no-repeat; background-position: right 0.5rem center; background-size: 1em;"
          >
            <option v-for="mod in availableModels" :key="mod" :value="mod">{{ mod }}</option>
          </select>
        </div>
      </header>

      <!-- Chat messages -->
      <div ref="chatContainer" class="flex-1 overflow-y-auto p-4 space-y-6 flex flex-col scroll-smooth items-center">
        <div
          v-for="msg in chatHistory"
          :key="msg.id"
          class="w-full max-w-3xl flex"
          :class="msg.role === 'user' ? 'justify-end' : 'justify-start'"
        >
          <div
            class="max-w-[85%] rounded-2xl px-6 py-4 shadow-sm transform transition-all whitespace-pre-wrap"
            :class="msg.role === 'user'
              ? 'bg-primary text-white rounded-br-sm shadow-md'
              : 'bg-white border border-neutral-200 rounded-bl-sm text-neutral-800'"
          >
            <!-- Typing indicator -->
            <div v-if="msg.content === '' && isLoading" class="flex items-center space-x-2 py-2 w-8">
              <div class="w-2 h-2 bg-neutral-400/60 rounded-full animate-bounce"></div>
              <div class="w-2 h-2 bg-neutral-400/60 rounded-full animate-bounce" style="animation-delay:0.15s"></div>
              <div class="w-2 h-2 bg-neutral-400/60 rounded-full animate-bounce" style="animation-delay:0.3s"></div>
            </div>
            <!-- Message content -->
            <div
              v-else
              class="leading-relaxed prose prose-emerald max-w-none prose-p:leading-relaxed prose-pre:bg-neutral-50 prose-pre:border prose-pre:border-neutral-200 prose-pre:text-neutral-800"
              :class="msg.role === 'user' ? 'prose-invert' : 'prose-slate'"
              v-html="marked.parse(msg.content)"
            ></div>
          </div>
        </div>

        <!-- Sources bar (after last assistant reply) -->
        <div
          v-if="!isLoading && lastSources.length > 0"
          class="w-full max-w-3xl flex items-center gap-2 flex-wrap pb-2"
        >
          <span class="text-[11px] text-neutral-400">Sources:</span>
          <span
            v-for="src in lastSources"
            :key="src"
            class="text-[11px] bg-white border border-neutral-200 text-neutral-600 px-2 py-0.5 rounded-full"
          >
            {{ src }}
          </span>
        </div>
      </div>

      <!-- Input -->
      <footer class="p-4 bg-transparent w-full pb-8">
        <form @submit.prevent="sendMessage" class="relative max-w-3xl mx-auto w-full">
          <input
            v-model="message"
            type="text"
            :placeholder="ragAvailable && hasIndexedFiles ? 'Ask about your documents…' : 'Send a message'"
            class="w-full bg-neutral-100 border-none text-neutral-900 placeholder-neutral-400 rounded-3xl pl-6 pr-14 py-4 focus:outline-none focus:ring-2 focus:ring-neutral-200 transition-all font-medium text-[15px] disabled:opacity-50 shadow-sm"
            :disabled="isLoading"
          />
          <button
            type="submit"
            class="absolute right-3 top-1/2 -translate-y-1/2 p-2 rounded-full transition-all flex items-center justify-center shadow-sm"
            :class="message.trim() && !isLoading
              ? 'bg-neutral-800 text-white hover:bg-neutral-700 cursor-pointer active:scale-95'
              : 'bg-neutral-300 text-white cursor-default'"
            :disabled="!message.trim() || isLoading"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none"
              stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
              <line x1="12" y1="19" x2="12" y2="5" />
              <polyline points="5 12 12 5 19 12" />
            </svg>
          </button>
        </form>
      </footer>
    </main>
  </div>
</template>
