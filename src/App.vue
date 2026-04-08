<script setup lang="ts">
import { ref, onMounted, watch, nextTick } from "vue";
import { chatStream, chatRAG, uploadDocument, getModels, type ChatMessage } from "./ollama";
import { marked } from "marked";

const message = ref("");
const isLoading = ref(false);
const chatHistory = ref<ChatMessage[]>([]);
const chatContainer = ref<HTMLElement | null>(null);


const MODEL_STORE_KEY = "local-ai-model-choice";

const availableModels = ref<string[]>([]);
const selectedModel = ref<string>("gemma4:e2b");
const isIngesting = ref(false);
const useRAG = ref(false);

const handleFileUpload = async (event: Event) => {
  const target = event.target as HTMLInputElement;
  if (!target.files || target.files.length === 0) return;
  
  const file = target.files[0];
  isIngesting.value = true;
  try {
    await uploadDocument(file, selectedModel.value);
    useRAG.value = true;
    chatHistory.value.push({
      id: Date.now(),
      role: "assistant",
      content: `I've successfully ingested **${file.name}** and added it to my knowledge base. You can now ask me questions about it!`
    });
    scrollToBottom();
  } catch (error: any) {
    alert("Error ingesting file: " + error.message);
  } finally {
    isIngesting.value = false;
    target.value = "";
  }
};

onMounted(() => {
  // Always start with a fresh chat
  chatHistory.value = [
    { id: Date.now(), role: "assistant", content: "Hello! I am your local AI assistant. How can I help you today?" }
  ];
  scrollToBottom();
  
  // Load models
  const savedModel = localStorage.getItem(MODEL_STORE_KEY);
  if (savedModel) {
    selectedModel.value = savedModel;
  }
  
  getModels().then(models => {
    availableModels.value = models;
    if (!models.includes(selectedModel.value) && models.length > 0) {
      selectedModel.value = models[0];
    }
  });
});

watch(selectedModel, (newVal) => {
  localStorage.setItem(MODEL_STORE_KEY, newVal);
});

watch(chatHistory, () => {
  scrollToBottom();
}, { deep: true });

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
  chatHistory.value.push({ id: Date.now(), role: "user", content: userMsg });
  
  const assistantId = Date.now() + 1;
  const assistantMsgRef = ref<ChatMessage>({ id: assistantId, role: "assistant", content: "" });
  chatHistory.value.push(assistantMsgRef.value);
  
  isLoading.value = true;
  
  try {
    if (useRAG.value) {
      const response = await chatRAG(userMsg, selectedModel.value);
      const index = chatHistory.value.findIndex(m => m.id === assistantId);
      if (index !== -1) {
        chatHistory.value[index].content = response;
      }
    } else {
      const stream = chatStream(chatHistory.value.slice(0, -1), selectedModel.value);
      for await (const chunk of stream) {
        const index = chatHistory.value.findIndex(m => m.id === assistantId);
        if (index !== -1) {
          chatHistory.value[index].content += chunk;
        }
      }
    }
  } catch (err: any) {
    const index = chatHistory.value.findIndex(m => m.id === assistantId);
    if (index !== -1) {
      chatHistory.value[index].content += `\n**Error:** ${err.message}`;
    }
  } finally {
    isLoading.value = false;
  }
};
</script>

<template>
  <main class="flex flex-col h-screen w-screen overflow-hidden bg-neutral-50 text-neutral-900">
    <!-- Header -->
    <header class="flex items-center justify-between p-4 border-b border-neutral-200 bg-white/70 backdrop-blur-md z-10 w-full shadow-sm">
      <div class="flex items-center gap-3">
        <div class="w-3 h-3 rounded-full animate-pulse shadow-sm" :class="isLoading ? 'bg-amber-500 shadow-amber-500/30' : 'bg-emerald-500 shadow-emerald-500/30'"></div>
        <h1 class="font-semibold tracking-wide text-lg text-neutral-800 font-mono">{{ selectedModel }}</h1>
      </div>
      <div class="flex items-center gap-4">
        <label 
          class="cursor-pointer text-sm px-4 py-2 rounded-md bg-white border border-neutral-200 text-neutral-700 hover:bg-neutral-50 transition-colors shadow-sm flex items-center gap-2"
          :class="{'opacity-50 pointer-events-none': isIngesting}"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
            <polyline points="17 8 12 3 7 8"></polyline>
            <line x1="12" y1="3" x2="12" y2="15"></line>
          </svg>
          <span v-if="!isIngesting" class="font-medium text-neutral-600 block sm:hidden md:block">Ingest File</span>
          <span v-else class="font-medium text-neutral-600 block sm:hidden md:block">Indexing...</span>
          <input type="file" class="hidden" @change="handleFileUpload" accept=".txt,.md,.pdf,.csv,.json" :disabled="isIngesting" />
        </label>
        <select 
          v-model="selectedModel" 
          class="text-sm px-3 py-1.5 rounded-md bg-white border border-neutral-200 text-neutral-700 hover:bg-neutral-50 transition-colors focus:outline-none focus:ring-2 focus:ring-primary/20 appearance-none cursor-pointer pr-8 relative shadow-sm"
          style="background-image: url('data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%2216%22 height=%2216%22 viewBox=%220 0 24 24%22 fill=%22none%22 stroke=%22%234b5563%22 stroke-width=%222%22 stroke-linecap=%22round%22 stroke-linejoin=%22round%22><polyline points=%226 9 12 15 18 9%22></polyline></svg>'); background-repeat: no-repeat; background-position: right 0.5rem center; background-size: 1em;"
        >
          <option v-for="mod in availableModels" :key="mod" :value="mod" class="bg-white text-neutral-900">{{ mod }}</option>
        </select>
      </div>
    </header>

    <!-- Chat Area -->
    <div ref="chatContainer" class="flex-1 overflow-y-auto p-4 space-y-6 flex flex-col scroll-smooth w-full items-center">
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
          <!-- Typing Indicator -->
          <div v-if="msg.content === '' && isLoading" class="flex items-center space-x-2 py-2 w-8">
            <div class="w-2 h-2 bg-neutral-400/60 rounded-full animate-bounce"></div>
            <div class="w-2 h-2 bg-neutral-400/60 rounded-full animate-bounce" style="animation-delay: 0.15s"></div>
            <div class="w-2 h-2 bg-neutral-400/60 rounded-full animate-bounce" style="animation-delay: 0.3s"></div>
          </div>
          <!-- Message Content -->
          <div v-else class="leading-relaxed prose prose-emerald max-w-none prose-p:leading-relaxed prose-pre:bg-neutral-50 prose-pre:border prose-pre:border-neutral-200 prose-pre:text-neutral-800" :class="msg.role === 'user' ? 'prose-invert' : 'prose-slate'" v-html="marked.parse(msg.content)"></div>
        </div>
      </div>
    </div>

    <!-- Input Area -->
    <footer class="p-4 bg-transparent w-full pb-8">
      <form @submit.prevent="sendMessage" class="relative max-w-3xl mx-auto w-full">
        <input 
          v-model="message"
          type="text" 
          placeholder="Send a message"
          class="w-full bg-neutral-100 border-none text-neutral-900 placeholder-neutral-400 rounded-3xl pl-6 pr-14 py-4 focus:outline-none focus:ring-2 focus:ring-neutral-200 transition-all font-medium text-[15px] disabled:opacity-50 shadow-sm"
          :disabled="isLoading"
        />
        <button 
          type="submit"
          class="absolute right-3 top-1/2 -translate-y-1/2 p-2 rounded-full transition-all flex items-center justify-center shadow-sm"
          :class="message.trim() && !isLoading ? 'bg-neutral-800 text-white hover:bg-neutral-700 cursor-pointer active:scale-95' : 'bg-neutral-300 text-white cursor-default'"
          :disabled="!message.trim() || isLoading"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <line x1="12" y1="19" x2="12" y2="5"></line>
            <polyline points="5 12 12 5 19 12"></polyline>
          </svg>
        </button>
      </form>
    </footer>
  </main>
</template>