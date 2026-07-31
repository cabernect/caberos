import { useState, useRef, useEffect } from "react";
import { Paperclip, FileText, Image as ImageIcon, Link, Wrench, ArrowUp, HelpCircle, Check } from "lucide-react";
import { ModelSelector } from "@/components/ModelSelector";

export interface Attachment {
  type: "image" | "url" | "file";
  mimeType: string;
  data: string; // base64 for images/files, URL for urls
  filename: string;
}

export interface ContextItem {
  type: "file" | "image" | "url" | "skill";
  label: string;
}

export interface ElicitationOption {
  label: string;
  description: string;
}

export interface ActiveElicitation {
  id: string;
  question: string;
  options: ElicitationOption[] | null;
  multiSelect: boolean;
}

interface ChatInputBarProps {
  defaultProviderId: string | null;
  defaultModelName: string | null;
  disabled?: boolean;
  onSend: (
    text: string,
    modelOverride: { provider_id: string; name: string } | null,
    context: ContextItem[],
    attachments?: Attachment[],
  ) => void;
  activeElicitation?: ActiveElicitation | null;
  onElicitationRespond?: (response: string) => void;
}

export function ChatInputBar({
  defaultProviderId,
  defaultModelName,
  disabled,
  onSend,
  activeElicitation,
  onElicitationRespond,
}: ChatInputBarProps) {
  const [text, setText] = useState("");
  const [modelOverride, setModelOverride] = useState<{
    provider_id: string;
    name: string;
  } | null>(null);
  const [contextItems, setContextItems] = useState<ContextItem[]>([]);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [showContextMenu, setShowContextMenu] = useState(false);
  const [showUrlInput, setShowUrlInput] = useState(false);
  const [urlValue, setUrlValue] = useState("");
  const [selectedOptions, setSelectedOptions] = useState<Set<number>>(new Set());
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const imageInputRef = useRef<HTMLInputElement>(null);

  const isElicitation = !!activeElicitation;

  useEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, 120) + "px";
  }, [text]);

  // Reset selected options when elicitation changes
  useEffect(() => {
    setSelectedOptions(new Set());
    if (isElicitation) {
      // Focus the textarea for free-text input
      setTimeout(() => textareaRef.current?.focus(), 50);
    }
  }, [activeElicitation?.id]);

  const handleSend = () => {
    if (isElicitation) {
      // Elicitation mode — send as elicitation response
      if (activeElicitation?.multiSelect && activeElicitation.options) {
        // Multi-select: send selected options + any typed text
        const selected = Array.from(selectedOptions)
          .sort((a, b) => a - b)
          .map((i) => activeElicitation.options![i].label);
        const all = text.trim() ? [...selected, text.trim()] : selected;
        if (all.length === 0) return;
        onElicitationRespond?.(all.join(", "));
      } else if (text.trim()) {
        onElicitationRespond?.(text.trim());
      }
      setText("");
      setSelectedOptions(new Set());
      return;
    }
    if (!text.trim() || disabled) return;
    onSend(text.trim(), modelOverride, contextItems, attachments.length > 0 ? attachments : undefined);
    setText("");
    setContextItems([]);
    setAttachments([]);
  };

  const handleOptionClick = (index: number) => {
    if (!activeElicitation) return;
    if (activeElicitation.multiSelect) {
      // Toggle selection
      setSelectedOptions((prev) => {
        const next = new Set(prev);
        if (next.has(index)) next.delete(index);
        else next.add(index);
        return next;
      });
    } else {
      // Single select — send immediately
      onElicitationRespond?.(activeElicitation.options![index].label);
    }
  };

  const fileToBase64 = (file: File): Promise<string> => {
    return new Promise((resolve) => {
      const reader = new FileReader();
      reader.onload = () => {
        const result = reader.result as string;
        // result is "data:mime;base64,..." — extract just the base64 part
        const base64 = result.split(",")[1] || "";
        resolve(base64);
      };
      reader.readAsDataURL(file);
    });
  };

  const handleImageSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files) return;
    for (const file of Array.from(files)) {
      const base64 = await fileToBase64(file);
      const att: Attachment = {
        type: "image",
        mimeType: file.type || "image/png",
        data: base64,
        filename: file.name,
      };
      setAttachments((prev) => [...prev, att]);
      setContextItems((prev) => [...prev, { type: "image", label: file.name }]);
    }
    setShowContextMenu(false);
    if (imageInputRef.current) imageInputRef.current.value = "";
  };

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files) return;
    for (const file of Array.from(files)) {
      if (file.type.startsWith("text/") || file.type === "application/json") {
        // Text file — read as text
        const content = await file.text();
        setAttachments((prev) => [...prev, {
          type: "file",
          mimeType: file.type || "text/plain",
          data: content,
          filename: file.name,
        }]);
      } else if (file.type.startsWith("image/")) {
        // Image file — read as base64
        const base64 = await fileToBase64(file);
        setAttachments((prev) => [...prev, {
          type: "image",
          mimeType: file.type,
          data: base64,
          filename: file.name,
        }]);
      } else {
        // Binary file — skip for now (PDF support can be added later)
        continue;
      }
      setContextItems((prev) => [...prev, { type: "file", label: file.name }]);
    }
    setShowContextMenu(false);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const handleUrlSubmit = () => {
    if (!urlValue.trim()) return;
    setAttachments((prev) => [...prev, {
      type: "url",
      mimeType: "image/jpeg", // assume image — model will handle
      data: urlValue.trim(),
      filename: "",
    }]);
    setContextItems((prev) => [...prev, { type: "url", label: urlValue.trim() }]);
    setUrlValue("");
    setShowUrlInput(false);
    setShowContextMenu(false);
  };

  const removeAttachment = (index: number) => {
    setAttachments(attachments.filter((_, i) => i !== index));
    setContextItems(contextItems.filter((_, i) => i !== index));
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (isElicitation) {
      // Number keys 1-9 to quick-select options (single select only)
      if (activeElicitation?.options && !activeElicitation.multiSelect) {
        const num = parseInt(e.key, 10);
        if (num >= 1 && num <= activeElicitation.options.length) {
          e.preventDefault();
          handleOptionClick(num - 1);
          return;
        }
      }
      // Number keys for multi-select toggle
      if (activeElicitation?.options && activeElicitation.multiSelect) {
        const num = parseInt(e.key, 10);
        if (num >= 1 && num <= activeElicitation.options.length) {
          e.preventDefault();
          handleOptionClick(num - 1);
          return;
        }
      }
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
      return;
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // (addContext/removeContext replaced by handleImageSelect/handleFileSelect/handleUrlSubmit/removeAttachment)

  return (
    <div
      className="px-4 py-3"
      style={{
        borderTop: "1px solid var(--border)",
        background: "var(--sidebar)",
      }}
    >
      {/* Elicitation panel — shown when agent asks a question */}
      {isElicitation && activeElicitation && (
        <div className="mx-auto mb-2 max-w-[672px] rounded-[6px] border"
          style={{ borderColor: "var(--warning)", background: "var(--surface)" }}
        >
          {/* Question header */}
          <div className="flex items-start gap-2 px-3 py-2.5"
            style={{ borderBottom: "1px solid var(--border)" }}
          >
            <HelpCircle className="mt-0.5 h-4 w-4 shrink-0" style={{ color: "var(--warning)" }} />
            <div className="text-[13px] leading-[1.5]" style={{ color: "var(--ink)" }}>
              {activeElicitation.question}
            </div>
          </div>

          {/* Options list */}
          {activeElicitation.options && activeElicitation.options.length > 0 && (
            <div className="py-1">
              {activeElicitation.options.map((opt, i) => {
                const selected = selectedOptions.has(i);
                return (
                  <button
                    key={i}
                    onClick={() => handleOptionClick(i)}
                    className="flex w-full items-start gap-2 px-3 py-1.5 text-left transition"
                    style={{
                      background: selected ? "var(--surface)" : "transparent",
                      cursor: "pointer",
                    }}
                    onMouseEnter={(e) => {
                      if (!selected) e.currentTarget.style.background = "var(--surface)";
                    }}
                    onMouseLeave={(e) => {
                      if (!selected) e.currentTarget.style.background = "transparent";
                    }}
                  >
                    <span
                      className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-[3px] border text-[10px] font-mono"
                      style={{
                        borderColor: selected ? "var(--warning)" : "var(--border)",
                        background: selected ? "var(--warning)" : "transparent",
                        color: selected ? "var(--white)" : "var(--ink-3)",
                      }}
                    >
                      {activeElicitation.multiSelect ? (
                        selected ? <Check className="h-3 w-3" /> : <span>{i + 1}</span>
                      ) : (
                        <span>{i + 1}</span>
                      )}
                    </span>
                    <div className="flex-1">
                      <div className="text-[13px] font-medium" style={{ color: "var(--ink)" }}>
                        {opt.label}
                      </div>
                      {opt.description && (
                        <div className="text-[11px] leading-[1.4]" style={{ color: "var(--ink-3)" }}>
                          {opt.description}
                        </div>
                      )}
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      )}

      <div className="mx-auto flex max-w-[672px] items-end gap-2">
        {/* Context chips above input */}
        {!isElicitation && contextItems.length > 0 && (
          <div className="absolute -top-9 left-0 flex flex-wrap gap-1.5">
            {contextItems.map((item, i) => (
              <span
                key={i}
                className="flex items-center gap-1 rounded-[5px] border px-2 py-1 text-[11px]"
                style={{
                  borderColor: "var(--border)",
                  background: "var(--white)",
                  color: "var(--ink-2)",
                }}
              >
                {item.type === "file" && <FileText className="h-3 w-3" />}
                {item.type === "image" && <ImageIcon className="h-3 w-3" />}
                {item.type === "url" && <Link className="h-3 w-3" />}
                {item.type === "skill" && <Wrench className="h-3 w-3" />}
                <span className="max-w-[150px] truncate font-mono">
                  {item.label}
                </span>
                <button
                  onClick={() => removeAttachment(i)}
                  className="text-[var(--ink-3)] hover:text-[var(--ink)]"
                >
                  ×
                </button>
              </span>
            ))}
          </div>
        )}

        {/* Model selector — hidden during elicitation */}
        {!isElicitation && (
          <ModelSelector
            defaultProviderId={defaultProviderId}
            defaultModelName={defaultModelName}
            onChange={setModelOverride}
          />
        )}

        {/* Attach button + context menu — hidden during elicitation */}
        {!isElicitation && (
        <div className="relative shrink-0">
          {/* Hidden file inputs */}
          <input
            ref={imageInputRef}
            type="file"
            accept="image/*"
            multiple
            style={{ display: "none" }}
            onChange={handleImageSelect}
          />
          <input
            ref={fileInputRef}
            type="file"
            accept="text/*,.json,.md,.py,.js,.ts,.tsx,.jsx,.yaml,.yml,.toml,.cfg,.ini,.txt,.csv,.log"
            multiple
            style={{ display: "none" }}
            onChange={handleFileSelect}
          />
          <button
            onClick={() => setShowContextMenu(!showContextMenu)}
            className="flex h-8 w-8 items-center justify-center rounded-[5px] border text-[var(--ink-2)] transition"
            style={{
              borderColor: "var(--border)",
              background: "none",
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.borderColor = "var(--ink-3)";
              e.currentTarget.style.color = "var(--ink)";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.borderColor = "var(--border)";
              e.currentTarget.style.color = "var(--ink-2)";
            }}
            title="Attach context"
          >
            <Paperclip className="h-3.5 w-3.5" />
          </button>
          {showContextMenu && (
            <>
              <div
                className="fixed inset-0 z-40"
                onClick={() => setShowContextMenu(false)}
              />
              <div
                className="absolute bottom-full left-0 z-50 mb-1 min-w-[180px] rounded-md border p-1 shadow-lg"
                style={{
                  borderColor: "var(--border)",
                  background: "var(--white)",
                  boxShadow: "0 4px 16px rgba(0,0,0,0.08)",
                }}
              >
                <ContextMenuItem
                  icon={<ImageIcon className="h-4 w-4" />}
                  label="Image"
                  onClick={() => imageInputRef.current?.click()}
                />
                <ContextMenuItem
                  icon={<FileText className="h-4 w-4" />}
                  label="Text file"
                  onClick={() => fileInputRef.current?.click()}
                />
                <ContextMenuItem
                  icon={<Link className="h-4 w-4" />}
                  label="URL"
                  onClick={() => { setShowUrlInput(true); setShowContextMenu(false); }}
                />
              </div>
            </>
          )}
          {showUrlInput && (
            <div
              className="absolute bottom-full left-0 z-50 mb-1 flex gap-1.5 rounded-md border p-2 shadow-lg"
              style={{
                borderColor: "var(--border)",
                background: "var(--white)",
                boxShadow: "0 4px 16px rgba(0,0,0,0.08)",
              }}
            >
              <input
                type="url"
                value={urlValue}
                onChange={(e) => setUrlValue(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") { e.preventDefault(); handleUrlSubmit(); }
                  if (e.key === "Escape") { setShowUrlInput(false); setUrlValue(""); }
                }}
                placeholder="https://example.com/image.jpg"
                className="w-[220px] rounded-[4px] px-2 py-1 text-[12px]"
                style={{ border: "1px solid var(--border)", background: "var(--white)", color: "var(--ink)" }}
                autoFocus
              />
              <button
                onClick={handleUrlSubmit}
                className="rounded-[4px] px-2 py-1 text-[12px] font-medium"
                style={{ background: "var(--ink)", color: "var(--white)", border: "none", cursor: "pointer" }}
              >
                Add
              </button>
            </div>
          )}
        </div>
        )}

        {/* Text input */}
        <textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={isElicitation
            ? (activeElicitation?.multiSelect
              ? "Add your own answer or select options above…"
              : "Or type your own answer…")
            : "Ask…"
          }
          rows={1}
          className="max-h-[120px] flex-1 resize-none rounded-[5px] py-1.5 px-3 font-sans text-[13px] leading-[1.6] outline-none transition"
          style={{
            background: "var(--white)",
            border: "1px solid var(--border)",
            color: "var(--ink)",
          }}
          onFocus={(e) => (e.currentTarget.style.borderColor = "var(--accent)")}
          onBlur={(e) => (e.currentTarget.style.borderColor = "var(--border)")}
        />

        {/* Send — enabled during elicitation if text or options selected */}
        {(() => {
          const canSend = isElicitation
            ? (text.trim() || selectedOptions.size > 0)
            : (text.trim() && !disabled);
          return (
          <button
            onClick={handleSend}
            disabled={!canSend}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[5px] border transition"
            style={{
              background: "var(--ink)",
              color: "var(--white)",
              borderColor: "var(--ink)",
              opacity: !canSend ? 0.35 : 1,
              cursor: !canSend ? "default" : "pointer",
            }}
            onMouseEnter={(e) => {
              if (!canSend) return;
              e.currentTarget.style.background = "var(--ink-2)";
              e.currentTarget.style.borderColor = "var(--ink-2)";
            }}
            onMouseLeave={(e) => {
              if (!canSend) return;
              e.currentTarget.style.background = "var(--ink)";
              e.currentTarget.style.borderColor = "var(--ink)";
            }}
          >
            <ArrowUp className="h-4 w-4" />
          </button>
          );
        })()}
      </div>
    </div>
  );
}

function ContextMenuItem({
  icon,
  label,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-[13px] transition"
      style={{ color: "var(--ink)" }}
      onMouseEnter={(e) => (e.currentTarget.style.background = "var(--surface)")}
      onMouseLeave={(e) => (e.currentTarget.style.background = "none")}
    >
      {icon}
      {label}
    </button>
  );
}
