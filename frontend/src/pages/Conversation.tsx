import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Settings, Send } from "lucide-react";
import { api, openStream } from "../lib/api";
import type { Message } from "../lib/types";

interface ChatMessage {
  id: string;
  role: string;
  content: string;
  created_at: string;
}

export function Conversation() {
  const { id: agentId } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamingText, setStreamingText] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const eventSourceRef = useRef<EventSource | null>(null);

  // Load history
  useEffect(() => {
    if (!agentId) return;
    api.getHistory(agentId)
      .then((msgs) => {
        setMessages(
          msgs.map((m: Message) => ({
            id: m.id,
            role: m.role,
            content: m.content,
            created_at: m.created_at,
          })),
        );
      })
      .catch(() => navigate("/login"));
  }, [agentId, navigate]);

  // Open SSE stream
  useEffect(() => {
    if (!agentId) return;

    const es = openStream(agentId);
    eventSourceRef.current = es;

    es.addEventListener("typing", () => {
      setIsStreaming(true);
    });

    es.addEventListener("token", (e) => {
      const data = JSON.parse(e.data);
      setStreamingText((prev) => prev + data.content);
    });

    es.addEventListener("message_complete", (e) => {
      const data = JSON.parse(e.data);
      if (data.status === "completed" && streamingText) {
        setMessages((prev) => [
          ...prev,
          {
            id: crypto.randomUUID(),
            role: "assistant",
            content: streamingText,
            created_at: new Date().toISOString(),
          },
        ]);
      }
      setStreamingText("");
      setIsStreaming(false);
    });

    es.addEventListener("heartbeat", () => {
      // keep-alive
    });

    return () => {
      es.close();
      eventSourceRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentId]);

  // Auto-scroll
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamingText, isStreaming]);

  const handleSend = async () => {
    if (!input.trim() || !agentId) return;
    const text = input.trim();
    setInput("");

    // Add user message immediately
    setMessages((prev) => [
      ...prev,
      {
        id: crypto.randomUUID(),
        role: "user",
        content: text,
        created_at: new Date().toISOString(),
      },
    ]);

    setStreamingText("");
    setIsStreaming(true);

    try {
      await api.sendMessage(agentId, text);
    } catch {
      setIsStreaming(false);
      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: "system",
          content: "Failed to send message",
          created_at: new Date().toISOString(),
        },
      ]);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="flex h-screen flex-col bg-[var(--color-background)]">
      {/* Top bar */}
      <header className="flex items-center justify-between border-b border-[var(--color-border)] px-6 py-3">
        <button
          onClick={() => navigate("/")}
          className="flex cursor-pointer items-center gap-2 text-sm text-[var(--color-secondary)] transition hover:text-[var(--color-text)]"
        >
          <ArrowLeft className="h-4 w-4" />
          Back
        </button>
        <span className="text-lg font-semibold text-[var(--color-text)]">
          {agentId}
        </span>
        <button className="cursor-pointer rounded-[var(--radius-md)] p-2 text-[var(--color-secondary)] transition hover:bg-[var(--color-surface)]">
          <Settings className="h-5 w-5" />
        </button>
      </header>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-6 py-8">
        <div className="mx-auto max-w-3xl space-y-4">
          {messages.map((msg) => (
            <MessageBubble key={msg.id} message={msg} />
          ))}

          {/* Streaming response */}
          {isStreaming && (
            <div className="max-w-[80%]">
              {streamingText ? (
                <div className="text-[var(--color-text)]">
                  {streamingText}
                  <span className="streaming-cursor" />
                </div>
              ) : (
                <TypingIndicator />
              )}
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Chat input */}
      <div className="border-t border-[var(--color-border)] px-6 py-4">
        <div className="mx-auto flex max-w-3xl items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask your agent..."
            rows={1}
            className="flex-1 resize-none rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface)] px-4 py-3 text-[var(--color-text)] outline-none focus:border-[var(--color-cta)]"
            style={{ minHeight: "48px", maxHeight: "200px" }}
          />
          <button
            onClick={handleSend}
            disabled={!input.trim()}
            className="flex h-12 w-12 cursor-pointer items-center justify-center rounded-[var(--radius-lg)] bg-[var(--color-cta)] text-white transition hover:opacity-90 disabled:opacity-50"
          >
            <Send className="h-5 w-5" />
          </button>
        </div>
      </div>
    </div>
  );
}

function MessageBubble({ message }: { message: ChatMessage }) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] rounded-[var(--radius-lg)] bg-[var(--color-surface)] px-4 py-3 text-[var(--color-text)]">
          {message.content}
        </div>
      </div>
    );
  }

  if (message.role === "heartbeat") {
    return (
      <div className="border-l-2 border-[var(--color-heartbeat)] pl-4 text-sm text-[var(--color-secondary)]">
        {message.content}
      </div>
    );
  }

  if (message.role === "system") {
    return (
      <div className="text-center text-xs text-[var(--color-secondary)]">
        {message.content}
      </div>
    );
  }

  // assistant
  return (
    <div className="max-w-[80%] text-[var(--color-text)]">
      {message.content}
    </div>
  );
}

function TypingIndicator() {
  return (
    <div className="flex gap-1 py-2">
      <div className="typing-dot h-2 w-2 rounded-full bg-[var(--color-secondary)]" />
      <div className="typing-dot h-2 w-2 rounded-full bg-[var(--color-secondary)]" />
      <div className="typing-dot h-2 w-2 rounded-full bg-[var(--color-secondary)]" />
    </div>
  );
}
