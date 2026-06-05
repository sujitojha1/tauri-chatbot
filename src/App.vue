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

// ── Theme toggle ───────────────────────────────────────────────────────────────
const THEME_STORE_KEY = "local-ai-theme-choice";
const isDarkMode = ref(false);

function toggleTheme() {
  isDarkMode.value = !isDarkMode.value;
  updateThemeClass();
}

function updateThemeClass() {
  if (isDarkMode.value) {
    document.documentElement.classList.add("dark");
    localStorage.setItem(THEME_STORE_KEY, "dark");
  } else {
    document.documentElement.classList.remove("dark");
    localStorage.setItem(THEME_STORE_KEY, "light");
  }
}

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
      pending: "text-slate-400 dark:text-slate-500",
      processing: "text-amber-500 dark:text-amber-400",
      chunked: "text-indigo-500 dark:text-indigo-400",
      indexed: "text-emerald-500 dark:text-emerald-400",
      failed: "text-rose-500 dark:text-rose-400",
    }[s] ?? "text-slate-400"
  );
}

function statusDot(s: FileStatus): string {
  return (
    {
      pending: "bg-slate-300 dark:bg-slate-600",
      processing: "bg-amber-400 animate-pulse",
      chunked: "bg-indigo-400 animate-pulse",
      indexed: "bg-emerald-400 dark:bg-emerald-500",
      failed: "bg-rose-400 dark:bg-rose-500",
    }[s] ?? "bg-slate-300"
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
    if (idx !== -1) chatHistory.value[idx].content += `\n\n**Error:** ${err.message}`;
  } finally {
    isLoading.value = false;
  }
};

// Start a fresh chat
function startFreshChat() {
  chatHistory.value = [
    {
      id: Date.now(),
      role: "assistant",
      content: "Hello! I am your local PD Checker assistant. How can I help you today?",
    },
  ];
  lastSources.value = [];
  scrollToBottom();
}

// ── Lifecycle ──────────────────────────────────────────────────────────────────
onMounted(async () => {
  // Theme initialization
  const savedTheme = localStorage.getItem(THEME_STORE_KEY);
  if (savedTheme === "dark" || (!savedTheme && window.matchMedia("(prefers-color-scheme: dark)").matches)) {
    isDarkMode.value = true;
  } else {
    isDarkMode.value = false;
  }
  updateThemeClass();

  // Load chat initialization
  startFreshChat();

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
  <div :class="{ 'dark': isDarkMode }" class="flex h-screen w-screen overflow-hidden bg-slate-50 text-slate-900 dark:bg-slate-950 dark:text-slate-100 transition-colors duration-300 font-sans">

    <!-- ── Left Sidebar ──────────────────────────────────────────────────────── -->
    <aside class="w-64 border-r border-slate-200/60 dark:border-slate-800/80 bg-white dark:bg-slate-900/60 backdrop-blur-md hidden md:flex flex-col shrink-0 z-20 transition-all duration-300">
      <!-- Sidebar header -->
      <div class="px-4 py-4 border-b border-slate-100 dark:border-slate-800/80 bg-white/50 dark:bg-slate-900/40">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-2">
            <div class="w-7 h-7 rounded-lg bg-indigo-600 flex items-center justify-center text-white shadow-md shadow-indigo-600/10">
              <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" />
              </svg>
            </div>
            <div>
              <h2 class="font-display font-bold text-slate-800 dark:text-slate-100 text-sm tracking-wide leading-none">
                PD <span class="text-indigo-600 dark:text-indigo-400">Checker</span>
              </h2>
              <span class="text-[9px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-widest mt-0.5 block">Local RAG</span>
            </div>
          </div>
          <div class="flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-800/80 border border-slate-200/20">
            <span class="w-1.5 h-1.5 rounded-full" :class="ragAvailable ? 'bg-emerald-400' : 'bg-slate-300 dark:bg-slate-600'"></span>
            <span class="text-[9px] font-semibold tracking-wider uppercase" :class="ragAvailable ? 'text-emerald-600 dark:text-emerald-400' : 'text-slate-400'">
              {{ ragAvailable ? 'online' : 'offline' }}
            </span>
          </div>
        </div>
      </div>

      <div class="flex-1 overflow-y-auto flex flex-col min-h-0 py-2">

        <!-- ── Global section ── -->
        <div class="flex flex-col min-h-0">
          <div class="flex items-center justify-between px-4 py-2">
            <span class="text-[10px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-wider">Global Store</span>
            <label
              class="flex items-center gap-1 text-[10px] font-bold px-2 py-1 rounded-lg border transition-all active:scale-95"
              :class="ragAvailable && !globalUploading
                ? 'cursor-pointer bg-white dark:bg-slate-800/50 border-slate-200 dark:border-slate-700/60 text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800'
                : 'cursor-not-allowed bg-slate-50 dark:bg-slate-900 border-slate-100 dark:border-slate-800 text-slate-300 dark:text-slate-700'"
              title="Add to global knowledge base"
            >
              <svg v-if="globalUploading" xmlns="http://www.w3.org/2000/svg" width="11" height="11" viewBox="0 0 24 24"
                fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"
                class="animate-spin"><path d="M21 12a9 9 0 1 1-6.219-8.56" /></svg>
              <svg v-else xmlns="http://www.w3.org/2000/svg" width="11" height="11" viewBox="0 0 24 24" fill="none"
                stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <path d="M12 5v14M5 12h14" />
              </svg>
              {{ globalUploading ? 'Adding…' : 'Add' }}
              <input ref="globalFileInput" type="file" class="hidden" multiple
                accept=".pdf,.docx,.txt,.md,.html,.pptx,.xlsx"
                :disabled="!ragAvailable || globalUploading" @change="handleGlobalUpload" />
            </label>
          </div>

          <div class="px-3 pb-3 space-y-2">
            <template v-if="!ragAvailable">
              <div class="bg-slate-50 dark:bg-slate-900/40 border border-slate-100 dark:border-slate-800/60 rounded-xl p-4 text-center">
                <p class="text-[10px] text-slate-400 dark:text-slate-500 leading-relaxed font-medium">
                  Start the RAG backend server to enable global document indexing.
                </p>
              </div>
            </template>
            <template v-else-if="globalFiles.length === 0">
              <div class="border border-dashed border-slate-200 dark:border-slate-800/80 rounded-xl py-6 text-center">
                <p class="text-[10px] font-medium text-slate-400 dark:text-slate-500">No global files indexed</p>
              </div>
            </template>
            
            <!-- Ingested Global File Card -->
            <div v-for="file in globalFiles" :key="file.id"
              class="group relative bg-white dark:bg-slate-900/40 border border-slate-150 dark:border-slate-800/70 rounded-xl p-3 hover:border-slate-300 dark:hover:border-slate-700/80 shadow-sm hover:shadow transition-all duration-200 ease-out">
              <div class="flex items-start justify-between gap-2">
                <div class="flex items-center gap-1.5 truncate flex-1">
                  <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" class="text-slate-400 dark:text-slate-500 shrink-0">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" />
                  </svg>
                  <span class="text-[11px] font-semibold text-slate-700 dark:text-slate-300 truncate" :title="file.filename">
                    {{ file.filename }}
                  </span>
                </div>
                <button @click="handleDeleteGlobal(file)"
                  class="opacity-0 group-hover:opacity-100 transition-all p-1 hover:bg-rose-50 dark:hover:bg-rose-950/30 text-slate-400 hover:text-rose-500 rounded-md shrink-0 cursor-pointer"
                  title="Remove document">
                  <svg xmlns="http://www.w3.org/2000/svg" width="11" height="11" viewBox="0 0 24 24" fill="none"
                    stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                    <polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                  </svg>
                </button>
              </div>
              <div class="mt-2 flex items-center justify-between gap-1">
                <span class="text-[10px] font-semibold text-slate-400 dark:text-slate-500">{{ file.size_human }}</span>
                <div class="flex items-center gap-1">
                  <span class="w-1.5 h-1.5 rounded-full shrink-0" :class="statusDot(file.status)"></span>
                  <span class="text-[10px] font-bold" :class="statusColor(file.status)">{{ statusLabel(file) }}</span>
                </div>
              </div>
              <div v-if="['pending','processing','chunked'].includes(file.status)"
                class="mt-2 h-1 bg-slate-100 dark:bg-slate-800 rounded-full overflow-hidden">
                <div class="h-full bg-indigo-500 animate-pulse rounded-full w-3/4"></div>
              </div>
              <p v-if="file.error" class="mt-1.5 text-[9px] font-semibold text-rose-500 truncate" :title="file.error">
                Error: {{ file.error }}
              </p>
            </div>
          </div>
        </div>

        <!-- ── Divider ── -->
        <div class="mx-4 my-2 border-t border-slate-100 dark:border-slate-800/80"></div>

        <!-- ── Session section ── -->
        <div class="flex flex-col min-h-0">
          <div class="flex items-center justify-between px-4 py-2">
            <span class="text-[10px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-wider">Session Store</span>
            <label v-if="ragAvailable"
              class="flex items-center gap-1 text-[10px] font-bold px-2 py-1 rounded-lg border transition-all active:scale-95 cursor-pointer bg-white dark:bg-slate-800/50 border-slate-200 dark:border-slate-700/60 text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800"
              :class="sessionUploading ? 'opacity-60 pointer-events-none' : ''"
              title="Add temporary files to this session only"
            >
              <svg v-if="sessionUploading" xmlns="http://www.w3.org/2000/svg" width="11" height="11" viewBox="0 0 24 24"
                fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"
                class="animate-spin"><path d="M21 12a9 9 0 1 1-6.219-8.56" /></svg>
              <svg v-else xmlns="http://www.w3.org/2000/svg" width="11" height="11" viewBox="0 0 24 24" fill="none"
                stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <path d="M12 5v14M5 12h14" />
              </svg>
              {{ sessionUploading ? 'Adding…' : 'Add' }}
              <input ref="sessionFileInput" type="file" class="hidden" multiple
                accept=".pdf,.docx,.txt,.md,.html,.pptx,.xlsx"
                :disabled="sessionUploading" @change="handleSessionUpload" />
            </label>
          </div>

          <div class="px-3 pb-3 space-y-2">
            <template v-if="!ragAvailable">
              <div class="bg-slate-50 dark:bg-slate-900/40 border border-slate-100 dark:border-slate-800/60 rounded-xl p-4 text-center">
                <p class="text-[10px] text-slate-400 dark:text-slate-500 font-medium">Session store requires RAG server.</p>
              </div>
            </template>
            <template v-else-if="sessionFiles.length === 0">
              <div class="border border-dashed border-slate-200 dark:border-slate-800/80 rounded-xl py-6 text-center">
                <p class="text-[10px] font-medium text-slate-400 dark:text-slate-500">Session store is empty</p>
              </div>
            </template>
            
            <!-- Ingested Session File Card -->
            <div v-for="file in sessionFiles" :key="file.id"
              class="group relative bg-blue-50/20 dark:bg-indigo-950/15 border border-indigo-100/40 dark:border-indigo-900/30 rounded-xl p-3 hover:border-indigo-200 dark:hover:border-indigo-800/80 shadow-sm hover:shadow transition-all duration-200 ease-out">
              <div class="flex items-start justify-between gap-2">
                <div class="flex items-center gap-1.5 truncate flex-1">
                  <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" class="text-indigo-400 dark:text-indigo-500 shrink-0">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" />
                  </svg>
                  <span class="text-[11px] font-semibold text-slate-700 dark:text-slate-300 truncate" :title="file.filename">
                    {{ file.filename }}
                  </span>
                </div>
                <button @click="handleDeleteSession(file)"
                  class="opacity-0 group-hover:opacity-100 transition-all p-1 hover:bg-rose-50 dark:hover:bg-rose-950/30 text-slate-400 hover:text-rose-500 rounded-md shrink-0 cursor-pointer"
                  title="Remove document">
                  <svg xmlns="http://www.w3.org/2000/svg" width="11" height="11" viewBox="0 0 24 24" fill="none"
                    stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                    <polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                  </svg>
                </button>
              </div>
              <div class="mt-2 flex items-center justify-between gap-1">
                <span class="text-[10px] font-semibold text-slate-400 dark:text-slate-500">{{ file.size_human }}</span>
                <div class="flex items-center gap-1">
                  <span class="w-1.5 h-1.5 rounded-full shrink-0" :class="statusDot(file.status)"></span>
                  <span class="text-[10px] font-bold" :class="statusColor(file.status)">{{ statusLabel(file) }}</span>
                </div>
              </div>
              <div v-if="['pending','processing','chunked'].includes(file.status)"
                class="mt-2 h-1 bg-slate-100 dark:bg-slate-800 rounded-full overflow-hidden">
                <div class="h-full bg-indigo-500 animate-pulse rounded-full w-3/4"></div>
              </div>
              <p v-if="file.error" class="mt-1.5 text-[9px] font-semibold text-rose-500 truncate" :title="file.error">
                Error: {{ file.error }}
              </p>
            </div>
          </div>
        </div>

      </div>
    </aside>

    <!-- ── Main Chat Area ───────────────────────────────────────────────────── -->
    <main class="flex flex-1 flex-col h-full overflow-hidden relative bg-slate-50/40 dark:bg-slate-950/40">

      <!-- Header -->
      <header class="flex items-center justify-between px-6 py-3 border-b border-slate-200/50 dark:border-slate-800/80 bg-white/75 dark:bg-slate-900/55 backdrop-blur-md z-10 w-full shadow-sm gap-3 transition-colors duration-300">
        <div class="flex items-center gap-3 min-w-0">
          <div
            class="w-2.5 h-2.5 rounded-full shadow-sm shrink-0"
            :class="isLoading ? 'bg-amber-400 animate-pulse' : 'bg-emerald-500'"
          ></div>
          
          <!-- Badge displaying active model -->
          <div class="flex items-center gap-2 font-mono text-xs bg-slate-100 dark:bg-slate-800/80 border border-slate-200/40 dark:border-slate-700/50 px-2.5 py-1 rounded-lg font-semibold text-slate-700 dark:text-slate-300">
            <svg xmlns="http://www.w3.org/2000/svg" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" class="text-indigo-500">
              <rect x="2" y="3" width="20" height="14" rx="2" ry="2" /><line x1="8" y1="21" x2="16" y2="21" /><line x1="12" y1="17" x2="12" y2="21" />
            </svg>
            {{ selectedModel }}
          </div>
          
          <!-- RAG mode pill -->
          <span v-if="ragAvailable && hasIndexedFiles"
            class="inline-flex items-center gap-1.5 text-[10px] font-bold px-2 py-0.5 rounded-full bg-emerald-50 dark:bg-emerald-950/20 text-emerald-600 dark:text-emerald-400 border border-emerald-250 dark:border-emerald-900/30 shrink-0">
            <span class="w-1 h-1 bg-emerald-400 dark:bg-emerald-500 rounded-full animate-ping"></span>RAG ACTIVE
          </span>
        </div>

        <div class="flex items-center gap-3 shrink-0">
          <!-- Model selector dropdown -->
          <div class="relative">
            <select
              v-model="selectedModel"
              class="text-xs font-semibold px-3 py-1.5 rounded-lg bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800/80 focus:ring-2 focus:ring-indigo-500/15 focus:border-indigo-500/60 transition-all appearance-none cursor-pointer pr-8 shadow-sm"
              style="background-image: url('data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%2214%22 height=%2214%22 viewBox=%220 0 24 24%22 fill=%22none%22 stroke=%22%2364748b%22 stroke-width=%222.5%22 stroke-linecap=%22round%22 stroke-linejoin=%22round%22><polyline points=%226 9 12 15 18 9%22></polyline></svg>'); background-repeat: no-repeat; background-position: right 0.6rem center; background-size: 0.9em;"
            >
              <option v-for="mod in availableModels" :key="mod" :value="mod">{{ mod }}</option>
            </select>
          </div>

          <!-- Actions -->
          <button @click="startFreshChat" class="p-1.5 rounded-lg bg-slate-100 hover:bg-slate-200/80 dark:bg-slate-850 dark:hover:bg-slate-800 text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-100 transition-all active:scale-95" title="Clear Chat History">
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
              <path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8" /><path d="M16 3h5v5" /><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16" /><path d="M8 21H3v-5" />
            </svg>
          </button>

          <!-- Theme toggle button -->
          <button @click="toggleTheme" class="p-1.5 rounded-lg bg-slate-100 hover:bg-slate-200/80 dark:bg-slate-850 dark:hover:bg-slate-800 text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-100 transition-all active:scale-90" :title="isDarkMode ? 'Light Mode' : 'Dark Mode'">
            <svg v-if="isDarkMode" xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" class="text-amber-400 rotate-0 transition-transform duration-300">
              <circle cx="12" cy="12" r="5" /><line x1="12" y1="1" x2="12" y2="3" /><line x1="12" y1="21" x2="12" y2="23" /><line x1="4.22" y1="4.22" x2="5.64" y2="5.64" /><line x1="18.36" y1="18.36" x2="19.78" y2="19.78" /><line x1="1" y1="12" x2="3" y2="12" /><line x1="21" y1="12" x2="23" y2="12" /><line x1="4.22" y1="19.78" x2="5.64" y2="18.36" /><line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
            </svg>
            <svg v-else xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" class="text-slate-600 rotate-12 transition-transform duration-300">
              <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
            </svg>
          </button>
        </div>
      </header>

      <!-- Chat messages -->
      <div ref="chatContainer" class="flex-1 overflow-y-auto px-6 py-6 space-y-6 flex flex-col scroll-smooth items-center">
        
        <!-- Welcome Screen Dashboard (shows only when chat history contains only the greeting) -->
        <div v-if="chatHistory.length <= 1" class="w-full max-w-2xl my-auto py-8 animate-slide-up">
          <div class="text-center mb-8">
            <div class="w-12 h-12 rounded-2xl bg-indigo-600 dark:bg-indigo-500 flex items-center justify-center text-white mx-auto shadow-xl shadow-indigo-600/20 mb-4 animate-bounce" style="animation-duration: 3s">
              <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
              </svg>
            </div>
            <h1 class="font-display font-extrabold text-2xl sm:text-3xl text-slate-800 dark:text-slate-100 tracking-tight">
              PD Checker <span class="bg-gradient-to-r from-indigo-500 to-indigo-600 dark:from-indigo-400 dark:to-indigo-500 bg-clip-text text-transparent">Desktop</span>
            </h1>
            <p class="mt-2 text-xs sm:text-sm text-slate-500 dark:text-slate-400 max-w-md mx-auto leading-relaxed">
              A private, local-first RAG chat assistant running entirely on your machine.
            </p>
          </div>

          <!-- Feature Cards Grid -->
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
            
            <div class="bg-white dark:bg-slate-900 border border-slate-200/50 dark:border-slate-800/80 rounded-2xl p-4 shadow-sm hover:shadow hover:border-slate-300 dark:hover:border-slate-700/80 transition-all duration-200">
              <div class="w-8 h-8 rounded-lg bg-indigo-50 dark:bg-indigo-950/40 text-indigo-600 dark:text-indigo-400 flex items-center justify-center mb-3">
                <svg xmlns="http://www.w3.org/2051/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                  <rect x="3" y="11" width="18" height="11" rx="2" ry="2" /><path d="M7 11V7a5 5 0 0 1 10 0v4" />
                </svg>
              </div>
              <h3 class="font-semibold text-xs text-slate-800 dark:text-slate-200 tracking-wide uppercase">100% Private & Local</h3>
              <p class="mt-1 text-[11px] text-slate-500 dark:text-slate-400 leading-normal">
                All document files, vector database instances, and chat inference run on your localhost.
              </p>
            </div>

            <div class="bg-white dark:bg-slate-900 border border-slate-200/50 dark:border-slate-800/80 rounded-2xl p-4 shadow-sm hover:shadow hover:border-slate-300 dark:hover:border-slate-700/80 transition-all duration-200">
              <div class="w-8 h-8 rounded-lg bg-emerald-50 dark:bg-emerald-950/40 text-emerald-600 dark:text-emerald-400 flex items-center justify-center mb-3">
                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                  <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
                </svg>
              </div>
              <h3 class="font-semibold text-xs text-slate-800 dark:text-slate-200 tracking-wide uppercase">Document Ingestion</h3>
              <p class="mt-1 text-[11px] text-slate-500 dark:text-slate-400 leading-normal">
                Upload PDFs, DOCX, TXT, or markdown. Ask questions grounded dynamically in your database.
              </p>
            </div>
          </div>
          
          <!-- System Status Details -->
          <div class="mt-6 p-4 rounded-2xl bg-slate-100/60 dark:bg-slate-900/40 border border-slate-200/20 flex flex-col gap-2.5">
            <div class="flex items-center justify-between text-xs font-semibold">
              <span class="text-slate-500 dark:text-slate-400">Ollama API Status</span>
              <span :class="availableModels.length > 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-500'" class="flex items-center gap-1.5">
                <span class="w-1.5 h-1.5 rounded-full" :class="availableModels.length > 0 ? 'bg-emerald-400' : 'bg-rose-400 animate-ping'"></span>
                {{ availableModels.length > 0 ? `${availableModels.length} models loaded` : 'Disconnected (Check Ollama)' }}
              </span>
            </div>
            
            <div class="flex items-center justify-between text-xs font-semibold">
              <span class="text-slate-500 dark:text-slate-400">RAG Server Connection</span>
              <span :class="ragAvailable ? 'text-emerald-600 dark:text-emerald-400' : 'text-amber-500'" class="flex items-center gap-1.5">
                <span class="w-1.5 h-1.5 rounded-full" :class="ragAvailable ? 'bg-emerald-400' : 'bg-amber-400'"></span>
                {{ ragAvailable ? 'Connected' : 'Offline (FastAPI server not running)' }}
              </span>
            </div>
          </div>
        </div>

        <!-- Rendered Chat History List -->
        <template v-else>
          <div
            v-for="msg in chatHistory"
            :key="msg.id"
            class="w-full max-w-3xl flex"
            :class="msg.role === 'user' ? 'justify-end' : 'justify-start'"
          >
            <!-- User bubble -->
            <div v-if="msg.role === 'user'"
              class="max-w-[85%] rounded-2xl rounded-tr-sm px-4.5 py-3 shadow-md shadow-indigo-500/5 bg-indigo-650 text-white font-medium text-[13px] leading-relaxed animate-slide-up"
            >
              {{ msg.content }}
            </div>

            <!-- Assistant bubble -->
            <div v-else
              class="w-full max-w-[85%] rounded-2xl rounded-tl-sm px-5 py-4.5 bg-white dark:bg-slate-900 border border-slate-200/60 dark:border-slate-800/80 text-slate-800 dark:text-slate-250 shadow-sm animate-slide-up relative"
            >
              <!-- Typing Indicator inside bubble -->
              <div v-if="msg.content === '' && isLoading" class="flex items-center space-x-1.5 py-1 w-8">
                <div class="w-1.5 h-1.5 bg-slate-400 dark:bg-slate-600 rounded-full animate-bounce"></div>
                <div class="w-1.5 h-1.5 bg-slate-400 dark:bg-slate-600 rounded-full animate-bounce" style="animation-delay:0.15s"></div>
                <div class="w-1.5 h-1.5 bg-slate-400 dark:bg-slate-600 rounded-full animate-bounce" style="animation-delay:0.3s"></div>
              </div>
              
              <!-- Markdown parsing of Assistant content -->
              <div
                v-else
                class="text-[13px] leading-relaxed prose prose-sm prose-slate dark:prose-invert max-w-none prose-p:my-1 prose-p:leading-relaxed prose-pre:bg-slate-950 dark:prose-pre:bg-black/40 prose-pre:border prose-pre:border-slate-800 prose-pre:rounded-xl prose-pre:p-3 prose-code:text-indigo-600 dark:prose-code:text-indigo-400 prose-code:bg-slate-100 dark:prose-code:bg-slate-850 prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-code:font-mono prose-ul:my-2 prose-li:my-0.5"
                v-html="marked.parse(msg.content)"
              ></div>
            </div>
          </div>
        </template>

        <!-- Sources bar (after last assistant reply) -->
        <div
          v-if="!isLoading && lastSources.length > 0 && chatHistory.length > 1"
          class="w-full max-w-3xl flex items-center gap-2 flex-wrap pb-4 animate-slide-up"
        >
          <span class="text-[10px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-wider">Sources:</span>
          <div
            v-for="src in lastSources"
            :key="src"
            class="text-[11px] font-medium bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 text-slate-600 dark:text-slate-400 px-3 py-0.5 rounded-full shadow-sm"
          >
            {{ src }}
          </div>
        </div>
      </div>

      <!-- Input footer -->
      <footer class="p-4 bg-transparent w-full pb-8">
        <form @submit.prevent="sendMessage" class="max-w-3xl mx-auto w-full">
          <div class="relative bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800/80 focus-within:ring-2 focus-within:ring-indigo-500/15 focus-within:border-indigo-500/60 rounded-2xl shadow-sm px-4.5 py-2.5 flex items-center transition-all duration-200">
            <input
              v-model="message"
              type="text"
              :placeholder="ragAvailable && hasIndexedFiles ? 'Ask about your documents…' : 'Type a message…'"
              class="flex-1 bg-transparent border-none outline-none focus:outline-none focus:ring-0 text-[13.5px] placeholder-slate-400 dark:placeholder-slate-500 text-slate-800 dark:text-slate-100 font-medium py-1 disabled:opacity-50"
              :disabled="isLoading"
            />
            
            <button
              type="submit"
              class="p-2 rounded-xl transition-all flex items-center justify-center shrink-0 cursor-pointer shadow-sm hover:shadow"
              :class="message.trim() && !isLoading
                ? 'bg-indigo-600 dark:bg-indigo-500 text-white hover:bg-indigo-500 dark:hover:bg-indigo-400 active:scale-95'
                : 'bg-slate-100 dark:bg-slate-800 text-slate-400 cursor-default'"
              :disabled="!message.trim() || isLoading"
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none"
                stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <line x1="12" y1="19" x2="12" y2="5" />
                <polyline points="5 12 12 5 19 12" />
              </svg>
            </button>
          </div>
        </form>
      </footer>
    </main>
  </div>
</template>

<style>
/* Override tailwind default input outline */
input:focus {
  outline: none !important;
  box-shadow: none !important;
}

/* User chat bubble specific custom color */
.bg-indigo-650 {
  background-color: #4f46e5;
}
</style>
