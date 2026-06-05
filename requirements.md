# Software Requirements Specification (SRS): AI Based PD Checker

This document defines the functional and non-functional requirements for the **AI Based PD Checker** application, conforming to the **IEEE 29148:2018** requirements engineering standard and formulated using the **Easy Approach to Requirements Syntax (EARS)**.

---

## 1. Project Objectives & System Overview

The **AI Based PD Checker** is a local-first desktop application designed to streamline product design audits. It allows engineering teams to import global product standards, load session-specific design mockups or specifications, automatically run structured compliance audits (generating evaluation tables), and engage in scoped follow-up Q&A.

---

## 2. Requirements Specification (EARS Syntax)

The system requirements are specified below. Each requirement is categorized by EARS patterns:
* **Ubiquitous**: *The system shall...*
* **State-driven**: *While [state], the system shall...*
* **Event-driven**: *When [event], the system shall...*
* **Unwanted Behavior**: *If [trigger], then the system shall...*

### 2.1 Functional Requirements (REQ-FN)

| Req ID | EARS Pattern | Requirement Statement |
|---|---|---|
| **REQ-FN-01** | Ubiquitous | The system shall allow users to upload global specification documents that persist across multiple sessions. |
| **REQ-FN-02** | State-driven | While in the **Specs Workspace**, if a user selects a specific specification document from the list, the system shall restrict all chat queries and RAG context retrieval strictly to that file. |
| **REQ-FN-03** | State-driven | While in the **Session Workspace**, if a design review has not yet been executed, the system shall display the Review Dashboard containing the loaded session files and hide the chat input. |
| **REQ-FN-04** | Event-driven | When the user clicks the "Run PD Review" button in the Session dashboard, the system shall execute a structured audit query against the session specification files and stream a compliance markdown table response. |
| **REQ-FN-05** | Event-driven | When the design review compliance output begins streaming, the system shall display the follow-up chat input container at the bottom. |
| **REQ-FN-06** | Ubiquitous | The system shall visually enable the message submit button at all times (always-on horizontal style) regardless of whether the message input text is populated. |
| **REQ-FN-07** | Event-driven | When the user clicks the hamburger button in either the sidebar or the main header, the system shall animate the collapse or expansion of the sidebar with a smooth width transition. |
| **REQ-FN-08** | Unwanted Behavior | If Qdrant collection names contain colons (`:`), the system shall sanitize them by replacing the colons with underscores (`_`) before calling any database APIs. |
| **REQ-FN-09** | Event-driven | When the user deletes a chat session, the system shall delete all database file metadata and Qdrant vectors associated with that session context. |

### 2.2 Non-Functional Requirements (REQ-NFR)

| Req ID | EARS Pattern | Requirement Statement |
|---|---|---|
| **REQ-NFR-01** | Ubiquitous | The system shall serialize and persist all chat histories, session file lists, selected spec files, and review statuses in `localStorage` across restarts. |
| **REQ-NFR-02** | Ubiquitous | The system shall process document parsing, text chunking, and embedding vectors on background thread pools to avoid blocking the main server execution loop. |
| **REQ-NFR-03** | Ubiquitous | The system shall fall back to local disk-based SQLite vector storage if a Docker-based Qdrant collection container is unavailable. |

---

## 3. Requirements Traceability Matrix (RTM)

The following matrix maps requirements to code components and files for complete traceability.

| Req ID | System Layer | Target Component / File | Implementation Reference |
|---|---|---|---|
| **REQ-FN-01** | Frontend/Backend | [App.vue](file:///c:/Users/gayad/dev/tauri-chatbot/src/App.vue) / [ingest.py](file:///c:/Users/gayad/dev/tauri-chatbot/backend/routers/ingest.py) | `handleGlobalUpload` streams to backend with context `"global"`. |
| **REQ-FN-02** | Frontend/Backend | [App.vue](file:///c:/Users/gayad/dev/tauri-chatbot/src/App.vue) / [query.py](file:///c:/Users/gayad/dev/tauri-chatbot/backend/routers/query.py) | `sendMessage` passes `fileId` to `ragChatStream`. `_retrieve` filters by `file_id`. |
| **REQ-FN-03** | Frontend | [App.vue](file:///c:/Users/gayad/dev/tauri-chatbot/src/App.vue) | `v-if="activeSession && !activeSession.isReviewed"` welcome view hides footer. |
| **REQ-FN-04** | Frontend/Backend | [App.vue](file:///c:/Users/gayad/dev/tauri-chatbot/src/App.vue) / [query.py](file:///c:/Users/gayad/dev/tauri-chatbot/backend/routers/query.py) | `runSessionReview` streams RAG compliance checklist prompt to Ollama. |
| **REQ-FN-05** | Frontend | [App.vue](file:///c:/Users/gayad/dev/tauri-chatbot/src/App.vue) | Input `<footer>` conditionally renders using `activeSession?.isReviewed`. |
| **REQ-FN-06** | Frontend | [App.vue](file:///c:/Users/gayad/dev/tauri-chatbot/src/App.vue) | Send button is styled with active classes and disabled state set to `isLoading`. |
| **REQ-FN-07** | Frontend/Style | [App.vue](file:///c:/Users/gayad/dev/tauri-chatbot/src/App.vue) / [styles.css](file:///c:/Users/gayad/dev/tauri-chatbot/src/styles.css) | `sidebarCollapsed` ref toggles classes. `.claude-sidebar` has transitions on width/opacity. |
| **REQ-FN-08** | Backend | [vector_store.py](file:///c:/Users/gayad/dev/tauri-chatbot/backend/services/vector_store.py) | `_clean` helper sanitizes incoming session collection names to valid Qdrant schemas. |
| **REQ-FN-09** | Backend | [ingest.py](file:///c:/Users/gayad/dev/tauri-chatbot/backend/routers/ingest.py) | `deleteSession` loops through file list and requests backend `DELETE /ingest/{id}`. |
| **REQ-NFR-01** | Frontend | [App.vue](file:///c:/Users/gayad/dev/tauri-chatbot/src/App.vue) | Setup watch triggers sync to `localStorage` under `SESSIONS_STORE_KEY`, etc. |
| **REQ-NFR-02** | Backend | [processor.py](file:///c:/Users/gayad/dev/tauri-chatbot/backend/workers/processor.py) | Background worker tasks execute CPU-bound parses/embeddings in `run_in_executor`. |
| **REQ-NFR-03** | Backend | [vector_store.py](file:///c:/Users/gayad/dev/tauri-chatbot/backend/services/vector_store.py) | `get_client` catches connection errors and initializes local fallback client. |
