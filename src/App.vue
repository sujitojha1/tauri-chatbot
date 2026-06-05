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
import appLogo from "./assets/app_logo.png";

// ── Theme toggle ───────────────────────────────────────────────────────────────
const THEME_STORE_KEY = "local-ai-theme-choice";
const isDarkMode = ref(false);

function toggleTheme() {
  isDarkMode.value = !isDarkMode.value;
  updateThemeClass();
}

// Active Tab in Sidebar ("chat" | "rag")
const activeTab = ref<"chat" | "rag">("chat");

function updateThemeClass() {
  if (isDarkMode.value) {
    document.documentElement.classList.add("dark");
    document.body.classList.add("dark");
    localStorage.setItem(THEME_STORE_KEY, "dark");
  } else {
    document.documentElement.classList.remove("dark");
    document.body.classList.remove("dark");
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
function statusDot(s: FileStatus): string {
  return (
    {
      pending: "bg-slate-300 dark:bg-slate-650",
      processing: "bg-amber-400 animate-pulse",
      chunked: "bg-indigo-400 animate-pulse",
      indexed: "bg-emerald-500 dark:bg-emerald-450",
      failed: "bg-rose-500 dark:bg-rose-450",
    }[s] ?? "bg-slate-300"
  );
}

const hasIndexedFiles = computed(
  () =>
    globalFiles.value.some((f) => f.status === "indexed") ||
    sessionFiles.value.some((f) => f.status === "indexed")
);

const allFiles = computed(() => {
  const unique = new Map<string, RagFile>();
  globalFiles.value.forEach(f => unique.set(f.id, f));
  sessionFiles.value.forEach(f => unique.set(f.id, f));
  return Array.from(unique.values());
});

async function handleDeleteFileUnified(file: RagFile) {
  watchers[file.id]?.();
  delete watchers[file.id];
  await deleteFile(file.id);
  globalFiles.value = globalFiles.value.filter((f) => f.id !== file.id);
  sessionFiles.value = sessionFiles.value.filter((f) => f.id !== file.id);
}

// ── Chat ───────────────────────────────────────────────────────────────────────
const showScrollDown = ref(false);

const handleScroll = (e: Event) => {
  const target = e.target as HTMLElement;
  showScrollDown.value = target.scrollHeight - target.scrollTop - target.clientHeight > 100;
};

const copyToClipboard = (text: string) => {
  navigator.clipboard.writeText(text).catch(err => {
    console.error("Failed to copy text: ", err);
  });
};

const scrollToBottom = () => {
  nextTick(() => {
    if (chatContainer.value) {
      chatContainer.value.scrollTop = chatContainer.value.scrollHeight;
      showScrollDown.value = false;
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
</script><template>
  <div :class="{ 'dark': isDarkMode }" class="layout-container font-sans transition-colors duration-300">
    
    <!-- ── Minimal Technical Drafting & Glow Backgrounds ── -->
    <div class="bg-decorations">
      <div class="drafting-grid"></div>
      <div class="drafting-circles"></div>
      <div class="orange-glow"></div>
    </div>

    <!-- ── Left Sidebar (Claude Flat Panel) ──────────────────────────────────── -->
    <aside class="claude-sidebar hidden md:flex flex-col z-10 transition-all duration-300">
      
      <!-- Chrome Controls Bar -->
      <div class="sidebar-chrome shrink-0">
        <div class="chrome-left">
          <button class="chrome-btn" title="Menu">
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
          </button>
          <button class="chrome-btn" title="Toggle Sidebar">
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><line x1="9" y1="3" x2="9" y2="21"/></svg>
          </button>
          <button class="chrome-btn" title="Search">
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
          </button>
        </div>
        <div class="flex items-center gap-1.5">
          <button class="chrome-btn" title="Go back">
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/></svg>
          </button>
          <button class="chrome-btn" title="Go forward">
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>
          </button>
        </div>
      </div>

      <!-- Segmented Tab block -->
      <div class="claude-tabs-block shrink-0">
        <div class="segmented-control">
          <button @click="activeTab = 'chat'" class="segmented-tab" :class="{ 'active': activeTab === 'chat' }">
            <svg xmlns="http://www.w3.org/2000/svg" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /></svg>
            Chat
          </button>
          <button @click="activeTab = 'rag'" class="segmented-tab" :class="{ 'active': activeTab === 'rag', 'opacity-50': !ragAvailable }">
            <svg xmlns="http://www.w3.org/2000/svg" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" /></svg>
            Specs
          </button>
        </div>
      </div>

      <!-- Action items -->
      <div class="claude-sidebar-actions-list shrink-0">
        <button @click="startFreshChat" class="claude-action-item">
          <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></svg>
          <span>New chat</span>
        </button>
      </div>

      <!-- Sidebar content scrolling list -->
      <div class="flex-1 overflow-y-auto flex flex-col min-h-0 py-2">
        
        <!-- Tab 1: Chat list -->
        <div v-show="activeTab === 'chat'" class="flex flex-col">
          <div class="recents-title">Recents</div>
          <div class="claude-history-item active truncate">
            <span class="truncate font-semibold text-[13px]">{{ chatHistory[1] ? chatHistory[1].content.substring(0, 32) + (chatHistory[1].content.length > 32 ? '...' : '') : 'Local RAG Chat' }}</span>
          </div>
        </div>

        <!-- Tab 2: Specs file manager -->
        <div v-show="activeTab === 'rag'" class="flex flex-col gap-2">
          <!-- Upload Specs Button Action -->
          <div class="px-2 py-1 shrink-0">
            <label
              class="claude-action-item cursor-pointer w-full flex items-center gap-2"
              :class="globalUploading ? 'opacity-50 pointer-events-none' : ''"
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
              <span>Upload specs</span>
              <input ref="globalFileInput" type="file" class="hidden" multiple accept=".pdf,.docx,.txt,.md,.html,.pptx,.xlsx" @change="handleGlobalUpload" />
            </label>
          </div>

          <!-- File List -->
          <div class="space-y-0.5 mt-2 overflow-y-auto min-h-0 flex-1">
            <div v-for="file in allFiles" :key="file.id" class="claude-history-item group relative">
              <div class="flex items-center gap-2 truncate flex-1">
                <svg xmlns="http://www.w3.org/2000/svg" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" class="text-slate-455 dark:text-slate-500 shrink-0">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" />
                </svg>
                <span class="truncate font-medium text-[12px] text-slate-700 dark:text-slate-300" :title="file.filename">{{ file.filename }}</span>
              </div>
              <span class="w-1.5 h-1.5 rounded-full shrink-0 mr-1.5" :class="statusDot(file.status)"></span>
              <button @click.stop="handleDeleteFileUnified(file)" class="opacity-0 group-hover:opacity-100 hover:text-rose-500 text-slate-450 cursor-pointer p-0.5 rounded transition-all shrink-0">
                <svg xmlns="http://www.w3.org/2000/svg" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" /></svg>
              </button>
            </div>
            
            <div v-if="allFiles.length === 0" class="text-center py-8 text-[11.5px] text-slate-400 dark:text-slate-500 font-medium select-none">
              No specifications uploaded
            </div>
          </div>
        </div>

      </div>

      <!-- Bottom Profile Bar -->
      <div class="claude-profile-container shrink-0">
        <div class="profile-info">
          <div class="profile-avatar select-none">so</div>
          <div class="profile-meta">
            Sujit <span class="pro-badge">· Pro</span>
          </div>
        </div>
      </div>

    </aside>

    <!-- ── Main Chat Area (Claude Flat Main) ─────────────────────────────────── -->
    <main class="claude-main">

      <!-- Header -->
      <header class="flex items-center justify-between px-6 py-4 border-b border-slate-100 dark:border-slate-800/80 bg-white dark:bg-slate-900/10 z-10 w-full transition-colors duration-300 shrink-0">
        <div class="flex items-center gap-2 min-w-0 cursor-pointer text-slate-800 dark:text-slate-100 hover:opacity-85 transition-all">
          <span class="font-display font-extrabold text-sm tracking-wide">
            {{ activeTab === 'rag' ? 'Document Database' : (chatHistory[1] ? chatHistory[1].content.substring(0, 45) + (chatHistory[1].content.length > 45 ? '...' : '') : 'Gradient descent step for linear regression') }}
          </span>
          <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" class="ml-0.5 text-slate-400"><polyline points="6 9 12 15 18 9" /></svg>
          <span v-if="isLoading" class="ml-3 text-[9px] font-bold tracking-widest text-indigo-600 dark:text-indigo-400 uppercase animate-pulse">generating…</span>
        </div>

        <div class="flex items-center gap-3.5 shrink-0">
          <!-- Document list icon & Share button -->
          <button class="chrome-btn text-slate-500 hover:text-slate-800" title="Attached resources">
            <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
          </button>
          <button class="chrome-btn text-slate-500 hover:text-slate-800" title="Share chat">
            <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8"/><polyline points="16 6 12 2 8 6"/><line x1="12" y1="2" x2="12" y2="15"/></svg>
          </button>

          <!-- Model selector dropdown -->
          <div class="relative">
            <select
              v-model="selectedModel"
              class="text-xs font-bold px-3 py-1.5 rounded-lg bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 text-slate-700 dark:text-slate-350 hover:bg-slate-50 dark:hover:bg-slate-800/80 focus:ring-2 focus:ring-indigo-500/15 focus:border-indigo-500/60 transition-all appearance-none cursor-pointer pr-8 shadow-sm"
              style="background-image: url('data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%2214%22 height=%2214%22 viewBox=%220 0 24 24%22 fill=%22none%22 stroke=%22%2364748b%22 stroke-width=%222.5%22 stroke-linecap=%22round%22 stroke-linejoin=%22round%22><polyline points=%226 9 12 15 18 9%22></polyline></svg>'); background-repeat: no-repeat; background-position: right 0.6rem center; background-size: 0.9em;"
            >
              <option v-for="mod in availableModels" :key="mod" :value="mod">{{ mod }}</option>
            </select>
          </div>

          <!-- Actions -->
          <button @click="startFreshChat" class="chrome-btn text-slate-500 hover:text-slate-800" title="Clear Chat History">
            <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
              <path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8" /><path d="M16 3h5v5" /><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16" /><path d="M8 21H3v-5" />
            </svg>
          </button>

        </div>
      </header>

      <!-- Chat messages container -->
      <div ref="chatContainer" @scroll="handleScroll" class="flex-1 overflow-y-auto px-6 py-8 space-y-8 flex flex-col scroll-smooth items-center">
        
        <!-- Welcome Screen Dashboard -->
        <div v-if="chatHistory.length <= 1" class="w-full max-w-2xl my-auto py-8"></div>

        <!-- Rendered Chat History List -->
        <template v-else>
          <div
            v-for="msg in chatHistory"
            :key="msg.id"
            class="w-full max-w-3xl flex"
            :class="msg.role === 'user' ? 'justify-end' : 'justify-start'"
          >
            <!-- User block container -->
            <div v-if="msg.role === 'user'" class="flex flex-col items-end gap-2 max-w-[75%]">
              
              <!-- Attached Document Card (Matching reference design) -->
              <div v-if="msg.id === chatHistory[1]?.id && hasIndexedFiles" class="flex items-center gap-3 bg-white dark:bg-slate-900 border border-slate-200/80 dark:border-slate-800 rounded-2xl p-3 shadow-sm select-none self-end max-w-sm mb-1">
                <div class="w-10 h-10 rounded-xl bg-rose-50 dark:bg-rose-950/20 flex items-center justify-center text-rose-500 shrink-0">
                  <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" /></svg>
                </div>
                <div class="flex-1 min-w-0 pr-4">
                  <p class="text-xs font-bold text-slate-800 dark:text-slate-200 truncate leading-snug">BoardingPass.pdf</p>
                  <span class="text-[9px] font-bold text-rose-500 uppercase tracking-widest mt-0.5 block">PDF</span>
                </div>
              </div>

              <!-- Actual User Bubble -->
              <div class="claude-bubble-user animate-slide-up">
                {{ msg.content }}
              </div>
            </div>

            <!-- Assistant bubble (Bubble-less Raw text) -->
            <div v-else
              class="w-full max-w-3xl flex flex-col gap-1 items-start"
            >
              <div class="claude-text-assistant animate-slide-up relative">
                <!-- Typing Indicator inside text -->
                <div v-if="msg.content === '' && isLoading" class="flex items-center space-x-1.5 py-2 w-8">
                  <div class="w-1.5 h-1.5 bg-slate-400 dark:bg-slate-600 rounded-full animate-bounce"></div>
                  <div class="w-1.5 h-1.5 bg-slate-400 dark:bg-slate-600 rounded-full animate-bounce" style="animation-delay:0.15s"></div>
                  <div class="w-1.5 h-1.5 bg-slate-400 dark:bg-slate-600 rounded-full animate-bounce" style="animation-delay:0.3s"></div>
                </div>
                
                <!-- Serif Markdown parsing of Assistant content -->
                <div
                  v-else
                  class="claude-prose"
                  v-html="marked.parse(msg.content)"
                ></div>
              </div>
              
              <!-- Action buttons under assistant message -->
              <div v-if="msg.content !== ''" class="claude-message-actions">
                <button @click="copyToClipboard(msg.content)" class="claude-action-btn" title="Copy response">
                  <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><rect x="9" y="9" width="13" height="13" rx="2" ry="2" /><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" /></svg>
                </button>
                <button class="claude-action-btn" title="Thumbs up">
                  <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3" /></svg>
                </button>
                <button class="claude-action-btn" title="Thumbs down">
                  <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zm12-5v9" /></svg>
                </button>
              </div>
            </div>
          </div>
        </template>

        <!-- Sources bar -->
        <div
          v-if="!isLoading && lastSources.length > 0 && chatHistory.length > 1"
          class="w-full max-w-3xl flex items-center gap-2 flex-wrap pb-4 animate-slide-up"
        >
          <span class="text-[9px] font-extrabold text-slate-400 dark:text-slate-500 uppercase tracking-widest">Sources:</span>
          <div
            v-for="src in lastSources"
            :key="src"
            class="text-[11px] font-bold bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700/50 text-slate-600 dark:text-slate-400 px-3.5 py-0.5 rounded-full shadow-sm"
          >
            {{ src }}
          </div>
        </div>
      </div>

      <!-- Input footer (Claude Dual-Row Pill Box) -->
      <footer class="p-5 bg-transparent w-full pb-6 shrink-0 relative">
        <!-- Floating scroll-down helper button -->
        <button v-if="showScrollDown" @click="scrollToBottom" class="scroll-down-btn animate-fade-in" title="Scroll to bottom">
          <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9" /></svg>
        </button>

        <form @submit.prevent="sendMessage" class="max-w-3xl mx-auto w-full">
          <div class="claude-input-container">
            <!-- Top Text input area -->
            <textarea
              v-model="message"
              rows="1"
              :placeholder="ragAvailable && hasIndexedFiles ? 'Ask about your documents…' : 'Write a message…'"
              class="claude-input-textarea"
              @keydown.enter.prevent="sendMessage"
              :disabled="isLoading"
            ></textarea>
            
            <!-- Bottom Row containing tools -->
            <div class="claude-input-toolbar">
              <div class="flex items-center gap-1">
                <!-- Plus button -->
                <button type="button" class="chrome-btn text-slate-400 hover:text-slate-800 dark:hover:text-slate-200" title="Attach content">
                  <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></svg>
                </button>
              </div>
              
              <div class="flex items-center gap-3.5">
                <!-- Active Model Info -->
                <span class="text-[11px] font-bold text-slate-400 dark:text-slate-550 select-none leading-none">{{ selectedModel }}</span>
                


                <!-- Send button inside toolbar -->
                <button
                  type="submit"
                  class="p-1 rounded-lg transition-all flex items-center justify-center cursor-pointer active:scale-95 ml-1"
                  :class="message.trim() && !isLoading
                    ? 'text-slate-850 dark:text-slate-100 hover:bg-slate-100 dark:hover:bg-slate-800'
                    : 'text-slate-300 dark:text-slate-700'"
                  :disabled="!message.trim() || isLoading"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" class="transform rotate-90">
                    <line x1="22" y1="2" x2="11" y2="13" /><polyline points="22 2 15 22 11 13 2 9 22 2" />
                  </svg>
                </button>
              </div>
            </div>
          </div>
          
          <!-- Legal disclaimer -->
          <div class="text-center mt-2">
            <span class="text-[11px] font-medium text-slate-400 dark:text-slate-650">
              PD Checker is AI and can make mistakes. Please double-check responses.
            </span>
          </div>
        </form>
      </footer>
    </main>
  </div>
</template>

<style>
/* Override default input focus ring outline */
input:focus, textarea:focus {
  outline: none !important;
  box-shadow: none !important;
}
</style>
