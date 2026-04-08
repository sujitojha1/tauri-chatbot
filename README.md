# Tauri Chatbot

A minimalistic, lightweight desktop chatbot application built with Tauri, Vue 3, and Vite.

## 🚀 Features

*   **Minimalistic UI:** Clean, distraction-free interface tailored for focused conversations.
*   **Built for Desktop:** Leveraging Tauri to provide a premium, native desktop experience with a minimal resource footprint.
*   **Modern Tech Stack:** Powered by Vue 3 (Composition API) and the ultra-fast Vite build tool.
*   **Local AI Powered:** Connects directly to your local [Ollama](https://ollama.com/) instance for intelligent, offline AI interactions.
*   **Privacy First:** Chat history, settings, and prompts natively remain local. No data is sent to the cloud.
*   **Knowledge Base Integration:** Upload files seamlessly to run accurate local Knowledge Graph RAG context queries completely utilizing LightRAG architecture.
*   **Markdown Support:** Rich text rendering in chat messages, complete with code syntax highlighting.
*   **Responsive & Fast:** Near-instant load times and smooth micro-animations for a premium feel.
*   **System Integration:** Native window controls and OS-level notifications.
*   **Theme Support:** Beautiful dark and light modes that adapt to your system preferences.

## 🛠️ Technology Stack

*   **[Tauri 2](https://v2.tauri.app/):** The core desktop application framework, using Rust for a secure, fast backend.
*   **[Vue 3](https://vuejs.org/):** The progressive frontend framework for building dynamic user interfaces.
*   **[Vite](https://vitejs.dev/):** Next-generation tooling for blazing fast development server and bundling.

## 📦 Getting Started

### Prerequisites

*   [Rust](https://www.rust-lang.org/tools/install)
*   [Node.js](https://nodejs.org/) (v16 or higher)
*   [npm](https://www.npmjs.com/) or [pnpm](https://pnpm.io/) or [yarn](https://yarnpkg.com/)
*   [Ollama](https://ollama.com/) (running locally with `gemma4:e2b` or your requested model)

### Setup & Development

1. Install the project's web dependencies:
   ```bash
   npm install
   ```
2. Start the LightRAG Python backend server in a separate terminal:
   ```bash
   cd backend
   ../venv/bin/python -m uvicorn server:app --port 8000
   ```
3. Start the Vite development server and the Tauri application window simultaneously:
   ```bash
   npm run tauri dev
   ```

### Building for Production

To compile a highly-optimized, standalone native application for your operating system (macOS/Windows/Linux):

```bash
npm run tauri build
```

After the build completes, your packaged installer and raw application executable (e.g. `.dmg` or `.app` for macOS) will be available in the `src-tauri/target/release/bundle/` directory.
