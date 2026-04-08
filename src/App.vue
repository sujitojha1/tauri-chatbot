<script setup lang="ts">
import { ref, onMounted, watch, nextTick } from "vue";
import { chatStream, type ChatMessage } from "./ollama";

const message = ref("");
const isLoading = ref(false);
const chatHistory = ref<ChatMessage[]>([]);
const chatContainer = ref<HTMLElement | null>(null);

const STORAGE_KEY = "local-ai-chat-history";

onMounted(() => {
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored) {
    try {
      chatHistory.value = JSON.parse(stored);
    } catch {
      chatHistory.value = [];
    }
  }
  if (chatHistory.value.length === 0) {
    chatHistory.value.push({ id: Date.now(), role: "assistant", content: "Hello! I am your local AI assistant. How can I help you today?" });
  }
  scrollToBottom();
});

watch(chatHistory, (newVal) => {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(newVal));
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
    const stream = chatStream(chatHistory.value.slice(0, -1));
    for await (const chunk of stream) {
      const index = chatHistory.value.findIndex(m => m.id === assistantId);
      if (index !== -1) {
        chatHistory.value[index].content += chunk;
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
  <main class="flex flex-col h-screen w-screen overflow-hidden bg-bg-dark text-fg-dark">
    <!-- Header -->
    <header class="flex items-center justify-between p-4 border-b border-white/10 bg-black/20 backdrop-blur-md z-10 w-full shadow-sm">
      <div class="flex items-center gap-3">
        <div class="w-3 h-3 rounded-full animate-pulse shadow-md" :class="isLoading ? 'bg-amber-500 shadow-amber-500/50' : 'bg-emerald-500 shadow-emerald-500/50'"></div>
        <h1 class="font-semibold tracking-wide text-lg text-white">Local AI Chatbot</h1>
      </div>
      <button class="text-sm px-3 py-1.5 rounded-md hover:bg-white/10 transition-colors">Settings</button>
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
          class="max-w-[85%] rounded-2xl px-5 py-3 shadow-sm transform transition-all whitespace-pre-wrap"
          :class="msg.role === 'user' 
            ? 'bg-primary text-white rounded-br-sm' 
            : 'bg-white/10 border border-white/5 rounded-bl-sm text-fg-dark'"
        >
          <!-- Typing Indicator -->
          <div v-if="msg.content === '' && isLoading" class="flex items-center space-x-2 py-2 w-8">
            <div class="w-2 h-2 bg-white/50 rounded-full animate-bounce"></div>
            <div class="w-2 h-2 bg-white/50 rounded-full animate-bounce" style="animation-delay: 0.15s"></div>
            <div class="w-2 h-2 bg-white/50 rounded-full animate-bounce" style="animation-delay: 0.3s"></div>
          </div>
          <!-- Message Content -->
          <p v-else class="leading-relaxed">{{ msg.content }}</p>
        </div>
      </div>
    </div>

    <!-- Input Area -->
    <footer class="p-4 bg-transparent w-full">
      <form @submit.prevent="sendMessage" class="relative max-w-3xl mx-auto w-full">
        <input 
          v-model="message"
          type="text" 
          placeholder="Message local AI..."
          class="w-full bg-white/5 border border-white/10 text-white placeholder-white/40 rounded-full pl-6 pr-14 py-3.5 focus:outline-none focus:ring-2 focus:ring-primary/50 transition-all font-medium disabled:opacity-50"
          :disabled="isLoading"
        />
        <button 
          type="submit"
          class="absolute right-2 top-1/2 -translate-y-1/2 p-2 bg-primary hover:bg-primary-hover text-white rounded-full transition-transform active:scale-95 flex items-center justify-center disabled:opacity-50 disabled:cursor-not-allowed"
          :disabled="!message.trim() || isLoading"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <line x1="22" y1="2" x2="11" y2="13"></line>
            <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
          </svg>
        </button>
      </form>
    </footer>
  </main>
</template>