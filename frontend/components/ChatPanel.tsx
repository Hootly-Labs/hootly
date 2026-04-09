import { useState, useEffect, useRef, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { getChatHistory, sendChatMessage, type ChatMessage } from "../lib/api";
import { useAuth } from "../lib/auth";

interface AnalysisResult {
  patterns?: { name: string; explanation?: string }[];
  key_files?: { path: string; explanation?: string }[];
  architecture?: { architecture_type?: string };
}

interface ChatPanelProps {
  analysisId: string;
  repoName: string;
  open: boolean;
  onClose: () => void;
  analysisResult?: AnalysisResult | null;
}

const DEFAULT_PROMPTS = [
  "How does auth work?",
  "What are the main entry points?",
  "What would break if I change the database models?",
  "How should I add a new API endpoint?",
  "Explain the architecture in simple terms",
];

function buildSuggestedPrompts(result?: AnalysisResult | null): string[] {
  if (!result) return DEFAULT_PROMPTS;

  const suggestions: string[] = [];

  // From architecture patterns
  const patterns = result.patterns || [];
  for (const p of patterns.slice(0, 2)) {
    if (p.name) suggestions.push(`How does ${p.name} work?`);
  }

  // From key files (pick 2 interesting ones)
  const keyFiles = result.key_files || [];
  const interesting = keyFiles
    .filter((f) => !f.path.includes("index.") && !f.path.includes("main."))
    .slice(0, 2);
  for (const f of interesting) {
    const name = f.path.split("/").pop() || f.path;
    suggestions.push(`What does ${name} do?`);
  }

  // Always include a general question
  suggestions.push("Explain the architecture in simple terms");

  // Pad with defaults if we don't have enough
  for (const d of DEFAULT_PROMPTS) {
    if (suggestions.length >= 5) break;
    if (!suggestions.includes(d)) suggestions.push(d);
  }

  return suggestions.slice(0, 5);
}

export default function ChatPanel({ analysisId, repoName, open, onClose, analysisResult }: ChatPanelProps) {
  const { user } = useAuth();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [streamText, setStreamText] = useState("");
  const [error, setError] = useState("");
  const [limitReached, setLimitReached] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const userMsgCount = messages.filter((m) => m.role === "user").length;
  const isFree = user?.plan === "free";
  const FREE_LIMIT = 10;

  // Load chat history on open
  useEffect(() => {
    if (open && !loaded) {
      getChatHistory(analysisId).then((msgs) => {
        setMessages(msgs);
        setLoaded(true);
        const userCount = msgs.filter((m) => m.role === "user").length;
        if (isFree && userCount >= FREE_LIMIT) setLimitReached(true);
      });
    }
  }, [open, analysisId, loaded, isFree]);

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamText]);

  // Focus input on open
  useEffect(() => {
    if (open && !limitReached) {
      setTimeout(() => inputRef.current?.focus(), 300);
    }
  }, [open, limitReached]);

  const handleSend = useCallback(async (text?: string) => {
    const message = (text || input).trim();
    if (!message || streaming) return;

    setInput("");
    setError("");
    setStreaming(true);
    setStreamText("");

    // Optimistically add user message
    const userMsg: ChatMessage = {
      id: `temp-${Date.now()}`,
      role: "user",
      content: message,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMsg]);

    await sendChatMessage(
      analysisId,
      message,
      // onDelta
      (delta) => {
        setStreamText((prev) => prev + delta);
      },
      // onDone
      (fullText) => {
        const assistantMsg: ChatMessage = {
          id: `temp-${Date.now()}-assistant`,
          role: "assistant",
          content: fullText,
          created_at: new Date().toISOString(),
        };
        setMessages((prev) => [...prev, assistantMsg]);
        setStreamText("");
        setStreaming(false);

        // Check free limit
        const newCount = userMsgCount + 1;
        if (isFree && newCount >= FREE_LIMIT) setLimitReached(true);
      },
      // onError
      (errMsg) => {
        if (errMsg === "FREE_CHAT_LIMIT_REACHED") {
          setLimitReached(true);
        } else {
          setError(errMsg);
        }
        setStreaming(false);
        setStreamText("");
      },
    );
  }, [input, streaming, analysisId, userMsgCount, isFree]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    if (open) window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/20 z-40 print:hidden"
        onClick={onClose}
      />

      {/* Panel */}
      <div className="fixed right-0 top-0 bottom-0 w-full max-w-lg bg-white dark:bg-slate-900 border-l border-slate-200 dark:border-slate-700 shadow-2xl z-50 flex flex-col animate-slide-in print:hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200 dark:border-slate-700 shrink-0">
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-lg">💬</span>
            <span className="font-semibold text-slate-900 dark:text-slate-100 truncate text-sm">
              Ask about {repoName}
            </span>
          </div>
          <div className="flex items-center gap-3 shrink-0">
            {isFree && (
              <span className="text-xs text-slate-400 dark:text-slate-500">
                {userMsgCount}/{FREE_LIMIT}
              </span>
            )}
            <button
              onClick={onClose}
              className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 transition-colors"
              title="Close (Esc)"
            >
              <svg className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
              </svg>
            </button>
          </div>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
          {messages.length === 0 && !streaming && (
            <div className="text-center py-8">
              <p className="text-slate-500 dark:text-slate-400 text-sm mb-6">
                Ask anything about this codebase. Answers are grounded in the analysis data.
              </p>
              <div className="flex flex-wrap gap-2 justify-center">
                {buildSuggestedPrompts(analysisResult).map((prompt) => (
                  <button
                    key={prompt}
                    onClick={() => handleSend(prompt)}
                    className="text-xs bg-slate-100 dark:bg-slate-800 hover:bg-blue-50 dark:hover:bg-blue-900/30 text-slate-600 dark:text-slate-400 hover:text-blue-700 dark:hover:text-blue-300 border border-slate-200 dark:border-slate-700 hover:border-blue-300 dark:hover:border-blue-600 rounded-full px-3 py-1.5 transition-colors"
                  >
                    {prompt}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((msg) => (
            <div
              key={msg.id}
              className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
            >
              <div
                className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm ${
                  msg.role === "user"
                    ? "bg-blue-600 text-white"
                    : "bg-slate-100 dark:bg-slate-800 text-slate-800 dark:text-slate-200"
                }`}
              >
                {msg.role === "assistant" ? (
                  <div className="chat-prose">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {msg.content}
                    </ReactMarkdown>
                  </div>
                ) : (
                  <p className="whitespace-pre-wrap">{msg.content}</p>
                )}
              </div>
            </div>
          ))}

          {/* Streaming message */}
          {streaming && (
            <div className="flex justify-start">
              <div className="max-w-[85%] rounded-2xl px-4 py-2.5 text-sm bg-slate-100 dark:bg-slate-800 text-slate-800 dark:text-slate-200">
                {streamText ? (
                  <div className="chat-prose">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {streamText}
                    </ReactMarkdown>
                  </div>
                ) : (
                  <div className="flex gap-1.5 py-1">
                    <span className="w-2 h-2 bg-slate-400 rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
                    <span className="w-2 h-2 bg-slate-400 rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
                    <span className="w-2 h-2 bg-slate-400 rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
                  </div>
                )}
              </div>
            </div>
          )}

          {error && (
            <div className="text-center">
              <p className="text-red-500 text-xs">{error}</p>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Input area */}
        <div className="border-t border-slate-200 dark:border-slate-700 p-3 shrink-0">
          {limitReached ? (
            <div className="text-center py-3">
              <p className="text-sm text-slate-600 dark:text-slate-400 mb-2">
                Free plan limit reached ({FREE_LIMIT} messages)
              </p>
              <a
                href="/settings"
                className="inline-block bg-blue-600 text-white text-sm font-medium px-4 py-2 rounded-lg hover:bg-blue-700 transition-colors"
              >
                Upgrade to Pro for unlimited chat
              </a>
            </div>
          ) : (
            <div className="flex items-end gap-2">
              <textarea
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask about the codebase..."
                rows={1}
                className="flex-1 resize-none border border-slate-200 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-200 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 max-h-32"
                style={{ minHeight: "2.5rem" }}
                disabled={streaming}
              />
              <button
                onClick={() => handleSend()}
                disabled={streaming || !input.trim()}
                className="bg-blue-600 text-white rounded-xl px-3 py-2 text-sm font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors shrink-0"
              >
                Send
              </button>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
