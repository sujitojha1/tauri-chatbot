<script setup lang="ts">
import { ref, onMounted, watch, nextTick, computed, onUnmounted } from "vue";
import { chatStream, getModels, type ChatMessage } from "./ollama";
import {
  uploadFile,
  deleteFile,
  reprocessFile,
  listFiles,
  watchFileStatus,
  ragChatStream,
  type RagFile,
  type FileStatus,
} from "./rag";
import { marked } from "marked";
import appLogo from "./assets/app_logo.png";

// ── Interfaces ─────────────────────────────────────────────────────────────────
interface ChatSession {
  id: string;
  title: string;
  history: ChatMessage[];
  sources: string[];
  files: RagFile[];
  isReviewed: boolean;
  created_at: number;
}



// Active Tab in Sidebar ("chat" | "rag")
const activeTab = ref<"chat" | "rag">("chat");
const sidebarCollapsed = ref(false);



// ── Model Selection ────────────────────────────────────────────────────────────
const MODEL_STORE_KEY = "local-ai-model-choice";
const availableModels = ref<string[]>([]);
const selectedModel = ref<string>("gemma4:e2b");

// ── Multi-Session State ────────────────────────────────────────────────────────
const SESSIONS_STORE_KEY = "pd-checker-sessions-list";
const CURRENT_SESSION_ID_KEY = "pd-checker-current-session-id";

const sessions = ref<ChatSession[]>([]);
const currentSessionId = ref<string>("");

// Computed active session
const activeSession = computed(() => {
  return sessions.value.find((s) => s.id === currentSessionId.value) || null;
});

// ── Inline session-title editing (top header) ──────────────────────────────────
const editingTitle = ref(false);
const titleDraft = ref("");
const titleInput = ref<HTMLInputElement | null>(null);

function startEditTitle() {
  if (!activeSession.value) return;
  titleDraft.value = activeSession.value.title;
  editingTitle.value = true;
  nextTick(() => {
    titleInput.value?.focus();
    titleInput.value?.select();
  });
}

function saveTitle() {
  if (!editingTitle.value) return; // guard against blur firing after enter/escape
  editingTitle.value = false;
  const next = titleDraft.value.trim();
  if (activeSession.value && next) {
    activeSession.value.title = next;
  }
}

function cancelEditTitle() {
  editingTitle.value = false;
}

// ── Specs Chat State (Chatting with individual files) ──────────────────────────
const FILE_CHAT_HISTORY_KEY = "pd-checker-file-chat-history";
const FILE_LAST_SOURCES_KEY = "pd-checker-file-last-sources";
const SELECTED_SPEC_FILE_ID_KEY = "pd-checker-selected-spec-file-id";

const selectedSpecFile = ref<RagFile | null>(null);
const fileChatHistory = ref<Record<string, ChatMessage[]>>({});
const fileLastSources = ref<Record<string, string[]>>({});

// ── Global Chat/Response State ─────────────────────────────────────────────────
const message = ref("");
const isLoading = ref(false);
const chatHistory = ref<ChatMessage[]>([]);
const chatContainer = ref<HTMLElement | null>(null);
const lastSources = ref<string[]>([]);

// ── RAG Backend Status ─────────────────────────────────────────────────────────
const ragAvailable = ref(false);

async function checkRagBackend() {
  try {
    const res = await fetch("http://localhost:8000/health");
    ragAvailable.value = res.ok;
  } catch {
    ragAvailable.value = false;
  }
}

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

function startWatcher(file: RagFile, type: "global" | "session") {
  if (watchers[file.id]) return;
  watchers[file.id] = watchFileStatus(
    file.id,
    (update) => {
      if (type === "global") {
        const idx = globalFiles.value.findIndex((f) => f.id === file.id);
        if (idx !== -1) {
          globalFiles.value[idx] = {
            ...globalFiles.value[idx],
            status: update.status,
            total_chunks: update.total_chunks,
            error: update.error,
          };
        }
      } else {
        const idx = sessionFiles.value.findIndex((f) => f.id === file.id);
        if (idx !== -1) {
          sessionFiles.value[idx] = {
            ...sessionFiles.value[idx],
            status: update.status,
            total_chunks: update.total_chunks,
            error: update.error,
          };
        }
      }
      // Also update matching items inside selectedSpecFile
      if (selectedSpecFile.value && selectedSpecFile.value.id === file.id) {
        selectedSpecFile.value = {
          ...selectedSpecFile.value,
          status: update.status,
          total_chunks: update.total_chunks,
          error: update.error,
        };
      }
    },
    () => {
      delete watchers[file.id];
      if (type === "global") {
        refreshGlobalFiles();
      } else {
        refreshSessionFiles();
      }
    }
  );
}

async function handleGlobalUpload(event: Event) {
  const filesList = (event.target as HTMLInputElement).files;
  if (!filesList?.length) return;

  globalUploading.value = true;
  for (const file of Array.from(filesList)) {
    try {
      const result = await uploadFile(file, "global");
      await refreshGlobalFiles();
      const record = globalFiles.value.find((f) => f.id === result.file_id);
      if (record) startWatcher(record, "global");
    } catch (e: any) {
      console.error("Upload failed:", e.message);
    }
  }
  globalUploading.value = false;
  if (globalFileInput.value) globalFileInput.value.value = "";
}

// ── Session Files (specs loaded for session review) ────────────────────────────
const sessionFiles = ref<RagFile[]>([]);
const sessionUploading = ref(false);
const sessionFileInput = ref<HTMLInputElement | null>(null);

// Which session's "three dots" options menu is currently open
const openMenuSessionId = ref<string | null>(null);
function toggleSessionMenu(id: string) {
  openMenuSessionId.value = openMenuSessionId.value === id ? null : id;
}

async function refreshSessionFiles() {
  if (!ragAvailable.value || !currentSessionId.value) return;
  sessionFiles.value = await listFiles(currentSessionId.value);
}

async function handleSessionUpload(event: Event) {
  const filesList = (event.target as HTMLInputElement).files;
  if (!filesList?.length || !currentSessionId.value) return;

  // Name the session after the first uploaded file (without extension) if still default
  const activeSess = sessions.value.find((s) => s.id === currentSessionId.value);
  if (activeSess && activeSess.title === "Review design") {
    const firstName = filesList[0].name.replace(/\.[^/.]+$/, "").trim();
    if (firstName) activeSess.title = firstName;
  }

  sessionUploading.value = true;
  for (const file of Array.from(filesList)) {
    try {
      const result = await uploadFile(file, currentSessionId.value);
      await refreshSessionFiles();
      const record = sessionFiles.value.find((f) => f.id === result.file_id);
      if (record) startWatcher(record, "session");
    } catch (e: any) {
      console.error("Session upload failed:", e.message);
    }
  }
  sessionUploading.value = false;
  if (sessionFileInput.value) sessionFileInput.value.value = "";
}

// ── Status Helpers ─────────────────────────────────────────────────────────────
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

async function handleDeleteFileUnified(file: RagFile) {
  watchers[file.id]?.();
  delete watchers[file.id];
  try {
    await deleteFile(file.id);
  } catch (e) {
    console.error("Delete call failed:", e);
  }
  globalFiles.value = globalFiles.value.filter((f) => f.id !== file.id);
  sessionFiles.value = sessionFiles.value.filter((f) => f.id !== file.id);
  
  if (selectedSpecFile.value && selectedSpecFile.value.id === file.id) {
    selectedSpecFile.value = null;
  }
}

// Re-run ingestion for a file that failed or never finished processing.
async function handleReprocessFile(file: RagFile, type: "global" | "session") {
  try {
    await reprocessFile(file.id);
  } catch (e) {
    console.error("Reprocess failed:", e);
    return;
  }
  // Optimistically reflect the pending state and (re)attach a status watcher.
  const patch = (f: RagFile): RagFile => ({
    ...f,
    status: "pending",
    error: null,
    total_chunks: null,
  });
  if (type === "global") {
    globalFiles.value = globalFiles.value.map((f) => (f.id === file.id ? patch(f) : f));
  } else {
    sessionFiles.value = sessionFiles.value.map((f) => (f.id === file.id ? patch(f) : f));
  }
  watchers[file.id]?.();
  delete watchers[file.id];
  startWatcher({ ...file, status: "pending" }, type);
}

// Open a file in the dedicated spec-chat view (works for global or session files).
function openFileChat(file: RagFile) {
  if (file.status !== "indexed") return;
  selectedSpecFile.value = file;
  activeTab.value = "rag";
}

// Reprocess a file that belongs to a specific session (Session tab list).
async function reprocessSessionFile(sessionId: string, file: RagFile) {
  try {
    await reprocessFile(file.id);
  } catch (e) {
    console.error("Reprocess failed:", e);
    return;
  }
  const patch = (f: RagFile): RagFile => ({
    ...f,
    status: "pending",
    error: null,
    total_chunks: null,
  });
  const sess = sessions.value.find((s) => s.id === sessionId);
  if (sess) sess.files = sess.files.map((f) => (f.id === file.id ? patch(f) : f));
  sessionFiles.value = sessionFiles.value.map((f) => (f.id === file.id ? patch(f) : f));
  watchers[file.id]?.();
  delete watchers[file.id];
  startWatcher({ ...file, status: "pending" }, "session");
}

// Delete a file that belongs to a specific session (Session tab list).
async function deleteSessionFile(sessionId: string, file: RagFile) {
  watchers[file.id]?.();
  delete watchers[file.id];
  try {
    await deleteFile(file.id);
  } catch (e) {
    console.error("Delete call failed:", e);
  }
  const sess = sessions.value.find((s) => s.id === sessionId);
  if (sess) sess.files = sess.files.filter((f) => f.id !== file.id);
  sessionFiles.value = sessionFiles.value.filter((f) => f.id !== file.id);
  if (selectedSpecFile.value && selectedSpecFile.value.id === file.id) {
    selectedSpecFile.value = null;
  }
}

// ── Scrolling & Clipboard helpers ──────────────────────────────────────────────
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

// ── Sending Chat Messages ──────────────────────────────────────────────────────
const sendMessage = async () => {
  if (!message.value.trim() || isLoading.value) return;

  const userMsg = message.value.trim();
  message.value = "";

  if (activeTab.value === 'chat') {
    // Session Chat (General followup)
    lastSources.value = [];
    chatHistory.value.push({ id: Date.now(), role: "user", content: userMsg });

    // Rename dynamic session if still default
    const activeSess = sessions.value.find(s => s.id === currentSessionId.value);
    if (activeSess && activeSess.title === "Review design") {
      activeSess.title = userMsg.substring(0, 32) + (userMsg.length > 32 ? '...' : '');
    }

    const assistantId = Date.now() + 1;
    chatHistory.value.push({ id: assistantId, role: "assistant", content: "" });
    isLoading.value = true;

    try {
      if (ragAvailable.value && hasIndexedFiles.value) {
        const stream = ragChatStream(
          chatHistory.value.slice(0, -1).map(({ role, content }) => ({ role, content })),
          selectedModel.value,
          currentSessionId.value
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
  } else if (activeTab.value === 'rag' && selectedSpecFile.value) {
    // Specs-scoped Individual File Chat
    const fileId = selectedSpecFile.value.id;
    if (!fileChatHistory.value[fileId]) {
      fileChatHistory.value[fileId] = [];
    }
    fileChatHistory.value[fileId].push({ id: Date.now(), role: "user", content: userMsg });

    if (!fileLastSources.value[fileId]) {
      fileLastSources.value[fileId] = [];
    }
    fileLastSources.value[fileId] = [];

    const assistantId = Date.now() + 1;
    fileChatHistory.value[fileId].push({ id: assistantId, role: "assistant", content: "" });
    isLoading.value = true;

    try {
      // Scope retrieval to the collection the file actually lives in:
      // global files sit in the global collection; session files in their session collection.
      const fileCtx = selectedSpecFile.value.context;
      const fileSessionId = fileCtx && fileCtx !== "global" ? fileCtx : undefined;
      const stream = ragChatStream(
        fileChatHistory.value[fileId].slice(0, -1).map(({ role, content }) => ({ role, content })),
        selectedModel.value,
        fileSessionId,
        fileId
      );
      for await (const event of stream) {
        if (event.type === "sources") {
          fileLastSources.value[fileId] = event.sources;
        } else {
          const idx = fileChatHistory.value[fileId].findIndex((m) => m.id === assistantId);
          if (idx !== -1) fileChatHistory.value[fileId][idx].content += event.token;
        }
      }
    } catch (err: any) {
      const idx = fileChatHistory.value[fileId].findIndex((m) => m.id === assistantId);
      if (idx !== -1) fileChatHistory.value[fileId][idx].content += `\n\n**Error:** ${err.message}`;
    } finally {
      isLoading.value = false;
      scrollToBottom();
    }
  }
};

// ── Run Compliance / design checklist review ──────────────────────────────────
const runSessionReview = async () => {
  const activeSess = sessions.value.find(s => s.id === currentSessionId.value);
  if (!activeSess || isLoading.value) return;

  activeSess.isReviewed = true;
  chatHistory.value = [];
  lastSources.value = [];

  const reviewPrompt = "Perform a thorough design compliance audit of the uploaded specifications. Cross-reference metrics, highlight gaps, and structure your findings in a detailed evaluation table listing Parameters, Requirements, and compliance status.";
  chatHistory.value.push({ id: Date.now(), role: "user", content: "Analyze specification compliance and generate the PD Evaluation Report." });

  const assistantId = Date.now() + 1;
  chatHistory.value.push({ id: assistantId, role: "assistant", content: "" });
  isLoading.value = true;

  try {
    if (ragAvailable.value && hasIndexedFiles.value) {
      const stream = ragChatStream(
        [{ role: "user", content: reviewPrompt }],
        selectedModel.value,
        currentSessionId.value
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
      const stream = chatStream([{ role: "user", content: reviewPrompt }], selectedModel.value);
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

// Start a fresh chat (Legacy/Backup)
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

// ── Multi-Session Actions ──────────────────────────────────────────────────────
function createNewSession() {
  const newId = `session:${Date.now()}`;
  const newSession: ChatSession = {
    id: newId,
    title: "Review design",
    history: [],
    sources: [],
    files: [],
    isReviewed: false,
    created_at: Date.now()
  };
  sessions.value.unshift(newSession);
  currentSessionId.value = newId;
  chatHistory.value = [];
  lastSources.value = [];
  sessionFiles.value = [];
}

async function deleteSession(id: string) {
  const idx = sessions.value.findIndex(s => s.id === id);
  if (idx === -1) return;

  const targetSession = sessions.value[idx];
  
  if (ragAvailable.value && targetSession.files) {
    for (const f of targetSession.files) {
      try {
        await deleteFile(f.id);
      } catch (e) {
        console.error("Failed to delete file on session deletion:", e);
      }
    }
  }

  sessions.value.splice(idx, 1);

  if (currentSessionId.value === id) {
    if (sessions.value.length > 0) {
      currentSessionId.value = sessions.value[0].id;
    } else {
      createNewSession();
    }
  }
}

// ── Lifecycle ──────────────────────────────────────────────────────────────────
onMounted(async () => {


  // Load model selection
  const savedModel = localStorage.getItem(MODEL_STORE_KEY);
  if (savedModel) selectedModel.value = savedModel;

  getModels().then((models) => {
    availableModels.value = models;
    if (!models.includes(selectedModel.value) && models.length > 0) {
      selectedModel.value = models[0];
    }
  });

  await checkRagBackend();

  // Load sessions from localStorage
  const savedSessions = localStorage.getItem(SESSIONS_STORE_KEY);
  const savedCurrentSessionId = localStorage.getItem(CURRENT_SESSION_ID_KEY);

  if (savedSessions) {
    try {
      sessions.value = JSON.parse(savedSessions);
    } catch (e) {
      sessions.value = [];
    }
  }

  // Load file chats history
  const savedFileChatHistory = localStorage.getItem(FILE_CHAT_HISTORY_KEY);
  const savedFileLastSources = localStorage.getItem(FILE_LAST_SOURCES_KEY);
  if (savedFileChatHistory) {
    try { fileChatHistory.value = JSON.parse(savedFileChatHistory); } catch (e) {}
  }
  if (savedFileLastSources) {
    try { fileLastSources.value = JSON.parse(savedFileLastSources); } catch (e) {}
  }

  if (sessions.value.length === 0) {
    createNewSession();
  } else {
    if (savedCurrentSessionId && sessions.value.some(s => s.id === savedCurrentSessionId)) {
      currentSessionId.value = savedCurrentSessionId;
      const s = sessions.value.find(s => s.id === savedCurrentSessionId);
      if (s) {
        chatHistory.value = [...s.history];
        lastSources.value = [...s.sources];
        sessionFiles.value = [...s.files];
      }
    } else {
      currentSessionId.value = sessions.value[0].id;
      chatHistory.value = [...sessions.value[0].history];
      lastSources.value = [...sessions.value[0].sources];
      sessionFiles.value = [...sessions.value[0].files];
    }
  }

  // Load active spec file selection
  const savedSelectedSpecFileId = localStorage.getItem(SELECTED_SPEC_FILE_ID_KEY);

  if (ragAvailable.value) {
    await refreshGlobalFiles();
    await refreshSessionFiles();
    
    // Resume watchers for global and active session files
    globalFiles.value
      .filter((f) => !["indexed", "failed"].includes(f.status))
      .forEach((f) => startWatcher(f, "global"));
    sessionFiles.value
      .filter((f) => !["indexed", "failed"].includes(f.status))
      .forEach((f) => startWatcher(f, "session"));

    if (savedSelectedSpecFileId) {
      const combined = [...globalFiles.value, ...sessionFiles.value];
      const match = combined.find(f => f.id === savedSelectedSpecFileId);
      if (match) selectedSpecFile.value = match;
    }
  }
});

onUnmounted(() => {
  Object.values(watchers).forEach((fn) => fn());
});

// ── Watchers ───────────────────────────────────────────────────────────────────
watch(selectedModel, (v) => localStorage.setItem(MODEL_STORE_KEY, v));
watch(chatHistory, scrollToBottom, { deep: true });

// Sync current session state changes back to sessions list
watch(chatHistory, (newVal) => {
  const session = sessions.value.find(s => s.id === currentSessionId.value);
  if (session) {
    session.history = [...newVal];
  }
}, { deep: true });

watch(lastSources, (newVal) => {
  const session = sessions.value.find(s => s.id === currentSessionId.value);
  if (session) {
    session.sources = [...newVal];
  }
}, { deep: true });

watch(sessionFiles, (newVal) => {
  const session = sessions.value.find(s => s.id === currentSessionId.value);
  if (session) {
    session.files = [...newVal];
  }
}, { deep: true });

// Sync lists to localStorage
watch(sessions, (newSessions) => {
  localStorage.setItem(SESSIONS_STORE_KEY, JSON.stringify(newSessions));
}, { deep: true });

watch(currentSessionId, (newId, oldId) => {
  localStorage.setItem(CURRENT_SESSION_ID_KEY, newId);
  
  if (oldId) {
    const oldSession = sessions.value.find(s => s.id === oldId);
    if (oldSession) {
      oldSession.history = [...chatHistory.value];
      oldSession.sources = [...lastSources.value];
      oldSession.files = [...sessionFiles.value];
    }
  }

  const newSession = sessions.value.find(s => s.id === newId);
  if (newSession) {
    chatHistory.value = [...newSession.history];
    lastSources.value = [...newSession.sources];
    sessionFiles.value = [...newSession.files];
    refreshSessionFiles();
  }
});

// Sync file chats
watch(fileChatHistory, (newHist) => {
  localStorage.setItem(FILE_CHAT_HISTORY_KEY, JSON.stringify(newHist));
}, { deep: true });

watch(fileLastSources, (newSrc) => {
  localStorage.setItem(FILE_LAST_SOURCES_KEY, JSON.stringify(newSrc));
}, { deep: true });

watch(selectedSpecFile, (newFile) => {
  if (newFile) {
    localStorage.setItem(SELECTED_SPEC_FILE_ID_KEY, newFile.id);
  } else {
    localStorage.removeItem(SELECTED_SPEC_FILE_ID_KEY);
  }
});
</script>

<template>
  <div class="layout-container font-sans transition-colors duration-300">
    
    <!-- ── Minimal Technical Drafting & Glow Backgrounds ── -->
    <div class="bg-decorations">
      <div class="drafting-grid"></div>
      <div class="drafting-circles"></div>
      <div class="orange-glow"></div>
    </div>

    <!-- Expand toggle — anchored to the same spot as the sidebar's menu button so it never shifts -->
    <button
      v-if="sidebarCollapsed"
      @click="sidebarCollapsed = false"
      class="chrome-btn absolute z-30"
      style="top: 14px; left: 16px;"
      title="Expand sidebar"
    >
      <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
    </button>

    <!-- ── Left Sidebar (Claude Flat Panel) ──────────────────────────────────── -->
    <aside :class="sidebarCollapsed ? '!w-0 !p-0 !border-r-0 overflow-hidden opacity-0 pointer-events-none' : 'w-[260px]'" class="claude-sidebar hidden md:flex flex-col z-10 transition-all duration-300">
      
      <!-- Chrome Controls Bar -->
      <div class="sidebar-chrome shrink-0">
        <div class="chrome-left">
          <button class="chrome-btn" title="Menu" @click="sidebarCollapsed = true">
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
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
            Session
          </button>
          <button @click="activeTab = 'rag'" class="segmented-tab" :class="{ 'active': activeTab === 'rag', 'opacity-50': !ragAvailable }">
            <svg xmlns="http://www.w3.org/2000/svg" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" /></svg>
            Specs
          </button>
        </div>
      </div>

      <!-- Sidebar Content Scrolling List -->
      <div class="flex-1 overflow-y-auto flex flex-col min-h-0 py-2">
        
        <!-- Tab 1: Chat Sessions list -->
        <div v-show="activeTab === 'chat'" class="flex flex-col">
          <div class="px-2 py-1 shrink-0">
            <button @click="createNewSession" class="claude-action-item">
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></svg>
              <span>Review</span>
            </button>
          </div>
          <div class="mx-3 my-1.5 border-t border-slate-200/60 dark:border-slate-800/60"></div>

          <div class="recents-title">Recents</div>
          <!-- Backdrop to close any open session menu on outside click -->
          <div v-if="openMenuSessionId" class="fixed inset-0 z-40" @click="openMenuSessionId = null"></div>

          <div class="flex flex-col gap-2.5 px-2">
            <div v-for="session in sessions" :key="session.id" class="flex flex-col gap-1">
              <!-- Session title item -->
              <div
                @click="currentSessionId = session.id"
                class="claude-history-item group relative flex items-center justify-between !mx-0 !my-0 cursor-pointer"
                :class="{ 'active': currentSessionId === session.id }"
              >
                <span class="flex items-center gap-1 truncate pr-6 min-w-0">
                  <!-- Expand/collapse chevron — only shown when the session has files to reveal -->
                  <svg
                    v-if="session.files && session.files.length > 0"
                    xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24"
                    fill="none" stroke="currentColor" stroke-width="2.5"
                    class="shrink-0 text-slate-400 dark:text-slate-500 transition-transform duration-200"
                    :class="{ 'rotate-90': currentSessionId === session.id }"
                  ><polyline points="9 18 15 12 9 6" /></svg>
                  <span class="truncate font-semibold text-[13px] select-none">
                    {{ session.title }}
                  </span>
                </span>

                <!-- Three-dot options trigger -->
                <button
                  @click.stop="toggleSessionMenu(session.id)"
                  class="opacity-0 group-hover:opacity-100 text-slate-400 dark:text-slate-500 hover:text-slate-700 dark:hover:text-slate-200 cursor-pointer p-0.5 rounded transition-all shrink-0 absolute right-2"
                  :class="{ '!opacity-100': openMenuSessionId === session.id }"
                  title="Options"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="5" r="1.5" /><circle cx="12" cy="12" r="1.5" /><circle cx="12" cy="19" r="1.5" /></svg>
                </button>

                <!-- Options dropdown -->
                <div
                  v-if="openMenuSessionId === session.id"
                  class="absolute right-2 top-9 z-50 min-w-[140px] bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl shadow-lg py-1"
                  @click.stop
                >
                  <button
                    @click="openMenuSessionId = null; deleteSession(session.id)"
                    class="w-full flex items-center gap-2 px-3 py-1.5 text-[12px] font-semibold text-rose-600 dark:text-rose-400 hover:bg-rose-50 dark:hover:bg-rose-950/30 transition-colors cursor-pointer"
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" /></svg>
                    Delete
                  </button>
                </div>
              </div>

              <!-- Uploaded files — expanded only for the selected session (accordion); others collapse -->
              <div v-if="currentSessionId === session.id && session.files && session.files.length > 0" class="flex flex-col gap-0.5 pl-3.5 mt-0.5">
                <div
                  v-for="file in session.files"
                  :key="file.id"
                  class="group/file flex items-center gap-1.5 text-[11px] font-medium text-slate-500 dark:text-slate-400 py-0.5 px-1.5 rounded-md hover:bg-slate-100/70 dark:hover:bg-slate-800/40 transition-colors"
                  :class="file.status === 'indexed' ? 'cursor-pointer hover:text-slate-700 dark:hover:text-slate-200' : 'cursor-default'"
                  :title="file.status === 'indexed' ? `Chat with ${file.filename}` : (file.error || file.filename)"
                  @click.stop="openFileChat(file)"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" class="shrink-0 text-slate-400 dark:text-slate-500">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" />
                  </svg>
                  <span class="truncate flex-1 min-w-0">{{ file.filename }}</span>

                  <!-- Retry processing (only when not indexed) -->
                  <button
                    v-if="file.status !== 'indexed'"
                    @click.stop="reprocessSessionFile(session.id, file)"
                    class="opacity-0 group-hover/file:opacity-100 p-0.5 rounded text-slate-400 hover:text-amber-500 transition-all shrink-0"
                    title="Retry processing"
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="23 4 23 10 17 10" /><polyline points="1 20 1 14 7 14" /><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" /></svg>
                  </button>
                  <!-- Delete -->
                  <button
                    @click.stop="deleteSessionFile(session.id, file)"
                    class="opacity-0 group-hover/file:opacity-100 p-0.5 rounded text-slate-400 hover:text-rose-500 transition-all shrink-0"
                    title="Remove file"
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" /><line x1="10" y1="11" x2="10" y2="17" /><line x1="14" y1="11" x2="14" y2="17" /></svg>
                  </button>
                  <span class="w-1.5 h-1.5 rounded-full shrink-0 group-hover/file:hidden" :class="statusDot(file.status)"></span>
                </div>
              </div>
            </div>
          </div>
        </div>
        
        <!-- Tab 2: Specs database -->
        <div v-show="activeTab === 'rag'" class="flex flex-col gap-2">
          <!-- Upload Specs Button -->
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

          <div class="mx-3 my-1.5 border-t border-slate-200/60 dark:border-slate-800/60"></div>
          
          <!-- Files List in Specs Sidebar (global specs only) -->
          <div class="recents-title !pt-0">Files</div>
          <div class="space-y-0.5 overflow-y-auto min-h-0 flex-1 px-1">
            <div
              v-for="file in globalFiles"
              :key="file.id"
              class="claude-history-item group flex items-center justify-between gap-1 !my-0.5 cursor-pointer"
              :class="{ 'active': selectedSpecFile && selectedSpecFile.id === file.id }"
              @click="selectedSpecFile = file"
            >
              <div class="flex items-center gap-2 truncate flex-1 min-w-0">
                <svg xmlns="http://www.w3.org/2000/svg" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" class="text-slate-455 dark:text-slate-500 shrink-0">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" />
                </svg>
                <span class="truncate font-medium text-[12px]" :title="file.error || file.filename">{{ file.filename }}</span>
              </div>

              <!-- Status dot (hidden on hover to reveal actions) -->
              <span class="w-1.5 h-1.5 rounded-full shrink-0 group-hover:hidden" :class="statusDot(file.status)"></span>
              <!-- Hover actions -->
              <div class="hidden group-hover:flex items-center gap-0.5 shrink-0">
                <button
                  v-if="file.status !== 'indexed'"
                  @click.stop="handleReprocessFile(file, 'global')"
                  class="text-slate-400 hover:text-amber-500 cursor-pointer p-0.5 rounded transition-all"
                  title="Retry processing"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="23 4 23 10 17 10" /><polyline points="1 20 1 14 7 14" /><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" /></svg>
                </button>
                <button
                  @click.stop="handleDeleteFileUnified(file)"
                  class="text-slate-400 hover:text-rose-500 cursor-pointer p-0.5 rounded transition-all"
                  title="Delete document"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" /><line x1="10" y1="11" x2="10" y2="17" /><line x1="14" y1="11" x2="14" y2="17" /></svg>
                </button>
              </div>
            </div>

            <div v-if="globalFiles.length === 0" class="text-center py-8 text-[11.5px] text-slate-400 dark:text-slate-500 font-medium select-none">
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
            Sujit Ojha
          </div>
        </div>
      </div>

    </aside>

    <!-- ── Main Chat Area (Claude Flat Main) ─────────────────────────────────── -->
    <main class="claude-main">

      <!-- Dynamic Header -->
      <header class="flex items-center justify-between px-6 py-4 border-b border-slate-100 dark:border-slate-800/80 bg-white dark:bg-slate-900/10 z-10 w-full transition-colors duration-300 shrink-0">
        <div class="flex items-center gap-2 min-w-0 text-slate-800 dark:text-slate-100 hover:opacity-85 transition-all" :class="{ 'pl-9': sidebarCollapsed }">
          <span class="font-display font-extrabold text-sm tracking-wide flex items-center gap-2">
            <!-- Back button if in file-scoped chat -->
            <button v-if="activeTab === 'rag' && selectedSpecFile" @click="selectedSpecFile = null" class="mr-1 p-1 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg text-slate-500" title="Back to Database">
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/></svg>
            </button>

            <!-- Specs tab: static title -->
            <template v-if="activeTab === 'rag'">
              {{ selectedSpecFile ? `Chatting with Spec: ${selectedSpecFile.filename}` : 'Specifications Hub' }}
            </template>

            <!-- Session tab: click-to-edit title -->
            <template v-else>
              <input
                v-if="editingTitle"
                ref="titleInput"
                v-model="titleDraft"
                @keydown.enter.prevent="saveTitle"
                @keydown.esc.prevent="cancelEditTitle"
                @blur="saveTitle"
                maxlength="80"
                class="font-display font-extrabold text-sm tracking-wide bg-transparent border-b border-indigo-400 dark:border-indigo-500 outline-none px-0.5 py-0.5 min-w-[140px] max-w-[460px] text-slate-800 dark:text-slate-100"
              />
              <button
                v-else
                @click="startEditTitle"
                class="group flex items-center gap-1.5 -mx-1 px-1 py-0.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800/60 transition-colors cursor-text"
                title="Click to rename"
              >
                <span class="truncate max-w-[460px]">{{ activeSession ? activeSession.title : 'Review design' }}</span>
                <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" class="text-slate-400 opacity-0 group-hover:opacity-100 transition-opacity shrink-0"><path d="M12 20h9" /><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z" /></svg>
              </button>
            </template>
          </span>
          <span v-if="isLoading" class="ml-3 text-[9px] font-bold tracking-widest text-indigo-600 dark:text-indigo-400 uppercase animate-pulse">generating…</span>
        </div>

        <div class="flex items-center gap-3.5 shrink-0">
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
        </div>
      </header>

      <!-- 1. SESSION MODE VIEW -->
      <div v-if="activeTab === 'chat'" class="flex-1 flex flex-col min-h-0 overflow-hidden">
        
        <!-- Welcome / Run Review Dashboard (Shown only if not reviewed yet) -->
        <div v-if="activeSession && !activeSession.isReviewed" class="flex-1 overflow-y-auto px-6 py-12 flex flex-col items-center justify-center text-center">
          <div class="w-full max-w-xl p-8 bg-slate-50/50 dark:bg-slate-900/10 border border-slate-200/50 dark:border-slate-800/40 rounded-3xl backdrop-blur-md shadow-xl flex flex-col items-center gap-6 animate-slide-up">
            <div class="w-16 h-16 rounded-2xl bg-amber-500/10 flex items-center justify-center text-amber-500">
              <svg xmlns="http://www.w3.org/2000/svg" width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>
            </div>
            
            <div>
              <h2 class="font-display font-extrabold text-2xl text-slate-800 dark:text-slate-100">AI Based PD Checker</h2>
              <p class="text-xs font-semibold text-slate-450 dark:text-slate-500 mt-2">
                Conduct structured Product Design audits and compliance checks on uploaded document specifications.
              </p>
            </div>

            <!-- Upload Specs inline area -->
            <div class="w-full bg-white dark:bg-slate-900/60 border border-slate-200/60 dark:border-slate-800 rounded-2xl p-4 text-left">
              <span class="text-[10px] font-bold uppercase tracking-widest text-slate-400 dark:text-slate-500">Specification files for this review</span>
              <div v-if="sessionFiles.length > 0" class="mt-2 space-y-2">
                <div v-for="file in sessionFiles" :key="file.id" class="group flex items-center justify-between gap-2 text-xs py-1 border-b border-slate-100 dark:border-slate-800/50">
                  <span class="truncate font-semibold text-slate-700 dark:text-slate-300 flex-1 min-w-0" :title="file.error || file.filename">{{ file.filename }}</span>
                  <div class="flex items-center gap-1 shrink-0">
                    <button
                      v-if="file.status !== 'indexed'"
                      @click="reprocessSessionFile(currentSessionId, file)"
                      class="opacity-0 group-hover:opacity-100 p-1 rounded-md text-slate-400 hover:text-amber-500 hover:bg-amber-50 dark:hover:bg-amber-950/30 transition-all"
                      title="Retry processing"
                    >
                      <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="23 4 23 10 17 10" /><polyline points="1 20 1 14 7 14" /><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" /></svg>
                    </button>
                    <button
                      @click="deleteSessionFile(currentSessionId, file)"
                      class="opacity-0 group-hover:opacity-100 p-1 rounded-md text-slate-400 hover:text-rose-500 hover:bg-rose-50 dark:hover:bg-rose-950/30 transition-all"
                      title="Remove file"
                    >
                      <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" /><line x1="10" y1="11" x2="10" y2="17" /><line x1="14" y1="11" x2="14" y2="17" /></svg>
                    </button>
                    <span class="w-1.5 h-1.5 rounded-full" :class="statusDot(file.status)"></span>
                  </div>
                </div>
              </div>
              <div v-else class="text-xs text-slate-400 dark:text-slate-500 py-4 text-center font-medium">
                No spec files yet. Add them with the button below.
              </div>

              <!-- Upload button trigger -->
              <label class="mt-3 cursor-pointer w-full flex items-center justify-center gap-1.5 py-2 px-3 border border-dashed border-slate-200 hover:border-slate-400 dark:border-slate-800 dark:hover:border-slate-600 rounded-xl text-xs font-semibold text-slate-600 dark:text-slate-350 hover:bg-slate-50 dark:hover:bg-slate-800/40 transition-all">
                <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></svg>
                Upload File for Review
                <input ref="sessionFileInput" type="file" class="hidden" multiple accept=".pdf,.docx,.txt,.md,.html,.pptx,.xlsx" @change="handleSessionUpload" />
              </label>
            </div>

            <!-- Run Review CTA button -->
            <button
              @click="runSessionReview"
              class="w-full py-3.5 px-6 rounded-2xl bg-amber-500 hover:bg-amber-600 active:scale-[0.99] font-bold text-sm text-white shadow-lg shadow-amber-500/15 flex items-center justify-center gap-2.5 transition-all cursor-pointer"
              :class="isLoading ? 'opacity-70 pointer-events-none' : ''"
            >
              <svg v-if="isLoading" class="animate-spin" xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 0 1 8-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 0 1 4 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"/></svg>
              <span v-if="isLoading">Running Audits...</span>
              <span v-else>Run PD Review</span>
            </button>
          </div>
        </div>

        <!-- Chat history feed (Unlocked once reviewed) -->
        <div v-else ref="chatContainer" @scroll="handleScroll" class="flex-1 overflow-y-auto px-6 py-8 space-y-8 flex flex-col scroll-smooth items-center">
          <div
            v-for="msg in chatHistory"
            :key="msg.id"
            class="w-full max-w-3xl flex"
            :class="msg.role === 'user' ? 'justify-end' : 'justify-start'"
          >
            <!-- User bubble -->
            <div v-if="msg.role === 'user'" class="claude-bubble-user animate-slide-up">
              {{ msg.content }}
            </div>

            <!-- Assistant compliance review tables / texts -->
            <div v-else class="w-full max-w-3xl flex flex-col gap-1 items-start">
              <div class="claude-text-assistant animate-slide-up relative">
                <!-- Loader -->
                <div v-if="msg.content === '' && isLoading" class="flex items-center space-x-1.5 py-2 w-8">
                  <div class="w-1.5 h-1.5 bg-slate-400 dark:bg-slate-650 rounded-full animate-bounce"></div>
                  <div class="w-1.5 h-1.5 bg-slate-400 dark:bg-slate-650 rounded-full animate-bounce" style="animation-delay:0.15s"></div>
                  <div class="w-1.5 h-1.5 bg-slate-400 dark:bg-slate-650 rounded-full animate-bounce" style="animation-delay:0.3s"></div>
                </div>
                
                <div v-else class="claude-prose" v-html="marked.parse(msg.content)"></div>
              </div>

              <!-- Action toolbar -->
              <div v-if="msg.content !== ''" class="claude-message-actions">
                <button @click="copyToClipboard(msg.content)" class="claude-action-btn" title="Copy response">
                  <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><rect x="9" y="9" width="13" height="13" rx="2" ry="2" /><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" /></svg>
                </button>
              </div>
            </div>
          </div>

          <!-- RAG Sources display -->
          <div
            v-if="!isLoading && lastSources.length > 0"
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

      </div>

      <!-- 2. SPECS MODE VIEW -->
      <div v-else class="flex-1 flex flex-col min-h-0 overflow-hidden">
        
        <!-- Case A: A file is selected for chatting -->
        <div v-if="selectedSpecFile" ref="chatContainer" @scroll="handleScroll" class="flex-1 overflow-y-auto px-6 py-8 space-y-8 flex flex-col scroll-smooth items-center">
          
          <!-- Welcome system chat message for file -->
          <div class="w-full max-w-3xl flex justify-start">
            <div class="claude-text-assistant animate-slide-up">
              <div class="claude-prose">
                <p>
                  You are now chatting with the specification file **{{ selectedSpecFile.filename }}**. 
                  All retrieved search queries will be strictly scoped and limited to this document. Ask any questions below.
                </p>
              </div>
            </div>
          </div>

          <!-- File specific chat history -->
          <template v-if="fileChatHistory[selectedSpecFile.id]">
            <div
              v-for="msg in fileChatHistory[selectedSpecFile.id]"
              :key="msg.id"
              class="w-full max-w-3xl flex"
              :class="msg.role === 'user' ? 'justify-end' : 'justify-start'"
            >
              <div v-if="msg.role === 'user'" class="claude-bubble-user animate-slide-up">
                {{ msg.content }}
              </div>
              
              <div v-else class="w-full max-w-3xl flex flex-col gap-1 items-start">
                <div class="claude-text-assistant animate-slide-up relative">
                  <div v-if="msg.content === '' && isLoading" class="flex items-center space-x-1.5 py-2 w-8">
                    <div class="w-1.5 h-1.5 bg-slate-400 dark:bg-slate-650 rounded-full animate-bounce"></div>
                    <div class="w-1.5 h-1.5 bg-slate-400 dark:bg-slate-650 rounded-full animate-bounce" style="animation-delay:0.15s"></div>
                    <div class="w-1.5 h-1.5 bg-slate-400 dark:bg-slate-650 rounded-full animate-bounce" style="animation-delay:0.3s"></div>
                  </div>
                  
                  <div v-else class="claude-prose" v-html="marked.parse(msg.content)"></div>
                </div>

                <div v-if="msg.content !== ''" class="claude-message-actions">
                  <button @click="copyToClipboard(msg.content)" class="claude-action-btn" title="Copy response">
                    <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><rect x="9" y="9" width="13" height="13" rx="2" ry="2" /><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" /></svg>
                  </button>
                </div>
              </div>
            </div>
          </template>

          <!-- File specific sources -->
          <div
            v-if="!isLoading && fileLastSources[selectedSpecFile.id] && fileLastSources[selectedSpecFile.id].length > 0"
            class="w-full max-w-3xl flex items-center gap-2 flex-wrap pb-4 animate-slide-up"
          >
            <span class="text-[9px] font-extrabold text-slate-400 dark:text-slate-500 uppercase tracking-widest">Sources:</span>
            <div
              v-for="src in fileLastSources[selectedSpecFile.id]"
              :key="src"
              class="text-[11px] font-bold bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700/50 text-slate-600 dark:text-slate-400 px-3.5 py-0.5 rounded-full shadow-sm"
            >
              {{ src }}
            </div>
          </div>
        </div>

        <!-- Case B: No file is selected (Landing Specs Hub Dashboard) -->
        <div v-else class="flex-1 overflow-y-auto px-8 py-8">
          <div class="w-full max-w-5xl mx-auto animate-slide-up">
            <!-- Compact intro row (the page title lives in the top header bar) -->
            <div class="flex items-center justify-between gap-4 mb-6">
              <p class="text-[13px] font-medium text-slate-500 dark:text-slate-400 max-w-xl">
                Global reference documents shared across every review. Select a file to chat with it directly.
              </p>
              <span v-if="globalFiles.length" class="shrink-0 text-[11px] font-bold uppercase tracking-wider text-slate-400 dark:text-slate-500">
                {{ globalFiles.length }} file{{ globalFiles.length === 1 ? '' : 's' }}
              </span>
            </div>

            <!-- Grid listing of global specifications -->
            <div v-if="globalFiles.length > 0" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              <div v-for="file in globalFiles" :key="file.id" class="p-4 bg-slate-50/50 dark:bg-slate-900/10 border border-slate-200/50 dark:border-slate-800/50 rounded-2xl flex flex-col justify-between gap-4 hover:shadow-md transition-all">
                <div class="flex items-start gap-3.5">
                  <div class="w-10 h-10 rounded-xl bg-indigo-500/10 flex items-center justify-center text-indigo-500 shrink-0">
                    <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                  </div>
                  <div class="min-w-0">
                    <h3 class="text-xs font-bold text-slate-800 dark:text-slate-200 truncate leading-snug" :title="file.filename">{{ file.filename }}</h3>
                    <div class="flex items-center gap-2 mt-1">
                      <span class="text-[9px] font-bold text-indigo-500 uppercase tracking-wider">{{ file.filename.split('.').pop() }}</span>
                      <span class="text-[10px] text-slate-400 font-medium">{{ file.size_human }}</span>
                      <span class="w-1.5 h-1.5 rounded-full" :class="statusDot(file.status)"></span>
                    </div>
                  </div>
                </div>

                <div class="flex items-center gap-2 w-full">
                  <button
                    @click="selectedSpecFile = file"
                    class="flex-1 py-2 rounded-xl bg-indigo-50 hover:bg-indigo-100 dark:bg-indigo-950/20 dark:hover:bg-indigo-950/40 text-[11px] font-bold text-indigo-600 dark:text-indigo-400 transition-all cursor-pointer text-center"
                    :disabled="file.status !== 'indexed'"
                    :class="file.status !== 'indexed' ? 'opacity-50 cursor-not-allowed' : ''"
                  >
                    Chat with Spec
                  </button>
                  <button
                    v-if="file.status !== 'indexed'"
                    @click="handleReprocessFile(file, 'global')"
                    class="p-2 rounded-xl bg-amber-50 hover:bg-amber-100 dark:bg-amber-950/20 dark:hover:bg-amber-950/40 text-amber-600 dark:text-amber-400 transition-all cursor-pointer"
                    title="Retry processing"
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="23 4 23 10 17 10" /><polyline points="1 20 1 14 7 14" /><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" /></svg>
                  </button>
                  <button
                    @click="handleDeleteFileUnified(file)"
                    class="p-2 rounded-xl bg-rose-50 hover:bg-rose-100 dark:bg-rose-950/20 dark:hover:bg-rose-950/40 text-rose-500 transition-all cursor-pointer"
                    title="Delete specification file"
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" /><line x1="10" y1="11" x2="10" y2="17" /><line x1="14" y1="11" x2="14" y2="17" /></svg>
                  </button>
                </div>
              </div>
            </div>

            <!-- Empty database state -->
            <div v-else class="text-center py-16 bg-slate-50/30 dark:bg-slate-900/5 border border-dashed border-slate-200 dark:border-slate-800 rounded-3xl">
              <div class="w-12 h-12 rounded-full bg-slate-100 dark:bg-slate-800 flex items-center justify-center text-slate-400 mx-auto mb-4">
                <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
              </div>
              <h3 class="text-sm font-bold text-slate-700 dark:text-slate-350">No global specifications loaded</h3>
              <p class="text-[11px] text-slate-400 mt-1 max-w-sm mx-auto">
                Upload global specifications here. For files specific to one review, use the Session tab.
              </p>
            </div>
          </div>
        </div>

      </div>

      <!-- Input Footer (Visually "always-on" submit button, only visible when chatting is unlocked) -->
      <footer v-if="(activeTab === 'chat' && activeSession?.isReviewed) || (activeTab === 'rag' && selectedSpecFile)" class="p-5 bg-transparent w-full pb-6 shrink-0 relative">
        <button v-if="showScrollDown" @click="scrollToBottom" class="scroll-down-btn animate-fade-in" title="Scroll to bottom">
          <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9" /></svg>
        </button>

        <form @submit.prevent="sendMessage" class="max-w-3xl mx-auto w-full">
          <div class="claude-input-container flex items-center gap-3">
            <button type="button" class="chrome-btn text-slate-400 hover:text-slate-800 dark:hover:text-slate-200 shrink-0" title="Attach content">
              <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></svg>
            </button>
            
            <input
              v-model="message"
              type="text"
              :placeholder="activeTab === 'rag' ? 'Ask about this specification document...' : 'Ask follow-up audit questions...'"
              class="flex-1 bg-transparent border-none outline-none focus:outline-none focus:ring-0 text-[13.5px] placeholder-slate-400 dark:placeholder-slate-500 text-slate-850 dark:text-slate-100 font-semibold py-1.5 disabled:opacity-50"
              @keydown.enter.prevent="sendMessage"
              :disabled="isLoading"
            />
            
            <!-- Send button: always visually on and clickable -->
            <button
              type="submit"
              class="p-1 rounded-lg transition-all flex items-center justify-center cursor-pointer active:scale-95 shrink-0 text-slate-850 dark:text-slate-100 hover:bg-slate-100 dark:hover:bg-slate-800"
              :disabled="isLoading"
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                <line x1="5" y1="12" x2="19" y2="12" /><polyline points="12 5 19 12 12 19" />
              </svg>
            </button>
          </div>
          
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
input:focus, textarea:focus {
  outline: none !important;
  box-shadow: none !important;
}
</style>
