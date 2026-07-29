import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Settings, Send, ArrowDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { api, openStream } from "@/lib/api";
import type { Message } from "@/lib/types";

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
  const [showJumpToLatest, setShowJumpToLatest] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const autoScrollRef = useRef(true);

  // Load history
  useEffect(() => {
    if (!agentId) return;
    api
      .getHistory(agentId)
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

  // Track scroll position to show/hide "jump to latest" button
  const handleScroll = () => {
    const container = scrollContainerRef.current;
    if (!container) return;
    const nearBottom =
      container.scrollHeight - container.scrollTop - container.clientHeight < 100;
    autoScrollRef.current = nearBottom;
    setShowJumpToLatest(!nearBottom);
  };

  // Auto-scroll when new content arrives (only if user is at bottom)
  useEffect(() => {
    if (autoScrollRef.current) {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages, streamingText, isStreaming]);

  const handleJumpToLatest = () => {
    autoScrollRef.current = true;
    setShowJumpToLatest(false);
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

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
    autoScrollRef.current = true;

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
    <div className="flex h-screen flex-col bg-background">
      {/* Top bar */}
      <header className="flex items-center justify-between border-b border-border px-6 py-3">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => navigate("/")}
        >
          <ArrowLeft className="h-4 w-4" />
          Back
        </Button>
        <span className="text-lg font-semibold text-foreground">{agentId}</span>
        <Button variant="ghost" size="icon-lg">
          <Settings className="h-5 w-5" />
        </Button>
      </header>

      {/* Messages */}
      <div
        ref={scrollContainerRef}
        onScroll={handleScroll}
        className="relative flex-1 overflow-y-auto px-6 py-8"
      >
        <div className="mx-auto max-w-3xl space-y-4">
          {messages.map((msg) => (
            <MessageBubble key={msg.id} message={msg} />
          ))}

          {/* Streaming response */}
          {isStreaming && (
            <div className="max-w-[80%]">
              {streamingText ? (
                <div className="text-foreground">
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

        {/* Jump to latest button */}
        {showJumpToLatest && (
          <Button
            variant="secondary"
            size="sm"
            onClick={handleJumpToLatest}
            className="absolute bottom-4 left-1/2 -translate-x-1/2 rounded-full shadow-lg"
          >
            <ArrowDown className="h-4 w-4" />
            Jump to latest
          </Button>
        )}
      </div>

      {/* Chat input */}
      <div className="border-t border-border px-6 py-4">
        <div className="mx-auto flex max-w-3xl items-end gap-2">
          <Textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask your agent..."
            rows={1}
            className="min-h-[48px] max-h-[200px] resize-none"
          />
          <Button
            onClick={handleSend}
            disabled={!input.trim()}
            size="icon-lg"
            className="h-12 w-12 shrink-0"
          >
            <Send className="h-5 w-5" />
          </Button>
        </div>
      </div>
    </div>
  );
}

function MessageBubble({ message }: { message: ChatMessage }) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] rounded-lg bg-card px-4 py-3 text-foreground">
          {message.content}
        </div>
      </div>
    );
  }

  if (message.role === "heartbeat") {
    return (
      <div className="border-l-2 border-[var(--color-heartbeat)] pl-4 text-sm text-muted-foreground">
        {message.content}
      </div>
    );
  }

  if (message.role === "system") {
    return (
      <div className="text-center text-xs text-muted-foreground">
        {message.content}
      </div>
    );
  }

  // assistant
  return <div className="max-w-[80%] text-foreground">{message.content}</div>;
}

function TypingIndicator() {
  return (
    <div className="flex gap-1 py-2">
      <div className="typing-dot h-2 w-2 rounded-full bg-muted-foreground" />
      <div className="typing-dot h-2 w-2 rounded-full bg-muted-foreground" />
      <div className="typing-dot h-2 w-2 rounded-full bg-muted-foreground" />
    </div>
  );
}
