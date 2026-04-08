# Development Plan: Tauri Chatbot

This document outlines the step-by-step phased approach for building the minimalistic Tauri + Vue 3 + Vite chatbot with local Ollama integration.

## Phase 1: Project Scaffolding
- [x] Initialize Tauri 2 project using Vue 3 and Vite template.
- [x] Install CSS framework (Tailwind CSS) for rapid, minimalistic UI styling.
- [x] Configure essential vite/tauri settings (app name, bundle identifiers, etc.).
- [x] Verify the basic application compiles and runs as a desktop window.

## Phase 2: Core User Interface Design
- [x] Design the primary application layout (sidebar/settings placeholder, main chat area).
- [x] Create basic Vue components:
    - `ChatWindow.vue`: To display the conversation history.
    - `MessageBubble.vue`: To render individual user or AI messages cleanly.
    - `ChatInput.vue`: The text input area for user prompts.
- [x] Implement foundational styles emphasizing minimalism (glassmorphism/subtle borders, refined typography).
- [x] Add basic dark/light mode toggle capabilities.

## Phase 3: State Management & Persistence
- [x] Setup a simple state store (using vue `ref` and `watch`) to hold messages (`id`, `role`, `content`).
- [x] Implement local storage to save chat history across sessions.
- [x] Ensure chat data is loaded automatically upon application startup.

## Phase 4: Local AI Integration (Ollama)
- [x] Create a service to handle HTTP requests to the local Ollama instance (typically `http://localhost:11434`).
- [x] Implement the logic to send user messages to the Ollama endpoint.
- [x] *(Advanced)* Implement streaming response parsing to show the AI typing in real-time.
- [x] Add basic error handling if Ollama is not running.

## Phase 5: Polish & Finalization
- [x] Incorporate a Markdown parser to correctly render AI responses (code blocks, bold text, etc.).
- [x] Add smooth scroll behaviors and subtle micro-animations (e.g., message entry transitions).
- [x] Perform final local tests on the macOS environment.
- [x] Finalize build configurations in `tauri.conf.json`.
