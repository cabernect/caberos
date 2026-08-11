import { useState, useRef, useEffect, useImperativeHandle, forwardRef } from "react";
import { Paperclip, FileText, Image as ImageIcon, Link, Wrench, ArrowUp, HelpCircle, Check, Sparkles, Square, Brain } from "lucide-react";
import { ModelSelector } from "@/components/ModelSelector";
import { api } from "@/lib/api";
import type { SkillInfo } from "@/lib/types";

export interface Attachment {
  type: "image" | "url" | "file";
  mimeType: string;
  data: string; // base64 for images/files, URL for urls
  filename: string;
}

export interface ChatInputBarHandle {
  addFiles: (files: File[]) => void;
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
    skill?: string,
  ) => void;
  onStop?: () => void;
  activeElicitation?: ActiveElicitation | null;
  onElicitationRespond?: (response: string) => void;
  contextTokens?: number;
  maxContextTokens?: number;
  compacted?: boolean;
  contextBreakdown?: { system_prompt: number; conversation: number; tools: number };
  onCompact?: () => void;
}

export const ChatInputBar = forwardRef<ChatInputBarHandle, ChatInputBarProps>(function ChatInputBar({
  defaultProviderId,
  defaultModelName,
  disabled,
  onSend,
  onStop,
  activeElicitation,
  onElicitationRespond,
  contextTokens,
  maxContextTokens,
  compacted,
  contextBreakdown,
  onCompact,
}, ref) {
  const [text, setText] = useState("");
  const [modelOverride, setModelOverride] = useState<{
    provider_id: string;
    name: string;
    supports_vision?: boolean;
    supports_thinking?: boolean;
    thinking_efforts?: string[];
  } | null>(null);
  const [thinkingEnabled, setThinkingEnabled] = useState<boolean | null>(null);
  const [thinkingEffort, setThinkingEffort] = useState<string>("medium");
  const [contextItems, setContextItems] = useState<ContextItem[]>([]);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [showContextMenu, setShowContextMenu] = useState(false);
  const [showUrlInput, setShowUrlInput] = useState(false);
  const [urlValue, setUrlValue] = useState("");
  const [selectedOptions, setSelectedOptions] = useState<Set<number>>(new Set());
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [skillQuery, setSkillQuery] = useState<string | null>(null);
  const [skillIndex, setSkillIndex] = useState(0);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const imageInputRef = useRef<HTMLInputElement>(null);

  const isElicitation = !!activeElicitation;

  // Load skills for slash command autocomplete
  useEffect(() => {
    api.listSkills().then((data) => setSkills(data.skills)).catch(() => {});
  }, []);

  // Detect slash command in text — only show autocomplete while typing the skill name
  // (not after a space, which means the user has moved on to their message)
  const slashMatch = !isElicitation && text.startsWith("/")
    ? text.match(/^\/([a-z0-9-]*)$/)
    : null;
  const skillQueryStr = slashMatch ? slashMatch[1] : null;

  // Built-in slash commands (always available, alongside skills)
  const builtinCommands = [
    { name: "compact", description: "Summarize older messages to free up context", isBuiltin: true },
  ];
  const filteredBuiltins = skillQueryStr !== null
    ? builtinCommands.filter((c) => c.name.startsWith(skillQueryStr))
    : [];
  const filteredSkills = skillQueryStr !== null
    ? skills.filter((s) => s.name.startsWith(skillQueryStr))
    : [];
  const allFiltered = [...filteredBuiltins, ...filteredSkills];
  const showSkillMenu = skillQueryStr !== null && allFiltered.length > 0;

  useEffect(() => {
    setSkillQuery(skillQueryStr);
    setSkillIndex(0);
  }, [skillQueryStr]);

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

    // Slash command detection: /skillname rest of message
    // Extracts the skill name and passes it separately to the backend
    let skill: string | undefined;
    let messageText = text.trim();
    const slashMatch = messageText.match(/^\/([a-z0-9-]+)\s*(.*)/s);
    if (slashMatch) {
      skill = slashMatch[1];
      messageText = slashMatch[2].trim() || messageText; // keep original if no text after skill
    }

    // Attach thinking params to the model override if the selected model supports it
    const overrideWithThinking = modelOverride
      ? {
          ...modelOverride,
          thinking_enabled: thinkingEnabled,
          thinking_effort: thinkingEnabled ? thinkingEffort : null,
        }
      : null;

    onSend(messageText, overrideWithThinking, contextItems, attachments.length > 0 ? attachments : undefined, skill);
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

  // Process dropped/selected files and add them as attachments.
  // Exposed via ref so the parent (Conversation) can forward drops
  // from the entire chat view, not just the input bar.
  const addFiles = async (files: File[]) => {
    if (isElicitation) return;
    for (const file of files) {
      if (file.type.startsWith("image/")) {
        const base64 = await fileToBase64(file);
        setAttachments((prev) => [...prev, {
          type: "image",
          mimeType: file.type || "image/png",
          data: base64,
          filename: file.name,
        }]);
      } else if (file.type.startsWith("text/") || file.type === "application/json") {
        const content = await file.text();
        setAttachments((prev) => [...prev, {
          type: "file",
          mimeType: file.type || "text/plain",
          data: content,
          filename: file.name,
        }]);
      } else {
        const base64 = await fileToBase64(file);
        setAttachments((prev) => [...prev, {
          type: "file",
          mimeType: file.type || "application/octet-stream",
          data: base64,
          filename: file.name,
        }]);
      }
      setContextItems((prev) => [...prev, { type: "file", label: file.name }]);
    }
  };

  useImperativeHandle(ref, () => ({ addFiles }), [isElicitation]);

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
      } else {
        // Binary file (PDF, docx, image, etc.) — read as base64, backend saves to workspace
        const base64 = await fileToBase64(file);
        setAttachments((prev) => [...prev, {
          type: "file",
          mimeType: file.type || "application/octet-stream",
          data: base64,
          filename: file.name,
        }]);
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
    // Ignore key events while IME is composing (e.g. Vietnamese, Chinese, Japanese).
    // The Enter that confirms the IME composition should NOT send the message.
    if (e.nativeEvent.isComposing || e.keyCode === 229) return;

    // Slash command autocomplete navigation
    if (showSkillMenu && !isElicitation) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSkillIndex((i) => Math.min(i + 1, filteredSkills.length - 1));
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setSkillIndex((i) => Math.max(i - 1, 0));
        return;
      }
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        const skill = filteredSkills[skillIndex];
        if (skill) {
          // Replace /query with /skillname + space
          const afterSlash = text.slice(slashMatch![0].length);
          setText(`/${skill.name} ${afterSlash}`.trim() + " ");
          return;
        }
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setSkillQuery(null);
        return;
      }
      if (e.key === "Tab") {
        e.preventDefault();
        const skill = filteredSkills[skillIndex];
        if (skill) {
          const afterSlash = text.slice(slashMatch![0].length);
          setText(`/${skill.name} ${afterSlash}`.trim() + " ");
        }
        return;
      }
    }

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

  // Drag-and-drop file upload
  const [isDragging, setIsDragging] = useState(false);
  const dragCounter = useRef(0);

  const handleDragEnter = (e: React.DragEvent) => {
    if (isElicitation) return;
    e.preventDefault();
    e.stopPropagation();
    dragCounter.current++;
    if (e.dataTransfer.types.includes("Files")) setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter.current--;
    if (dragCounter.current === 0) setIsDragging(false);
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  };

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter.current = 0;
    setIsDragging(false);
    if (isElicitation) return;
    await addFiles(Array.from(e.dataTransfer.files));
  };

  return (
    <div
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
      className="relative px-4 py-3"
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

      {/* Vision warning — image attached but selected model doesn't support vision */}
      {!isElicitation && modelOverride && modelOverride.supports_vision === false &&
        attachments.some((a) => a.type === "image") && (
        <div className="mx-auto mb-2 flex max-w-[672px] items-center gap-2 rounded-[5px] border px-3 py-1.5 text-[12px]"
          style={{ borderColor: "var(--warning)", background: "var(--surface)", color: "var(--ink-2)" }}
        >
          <ImageIcon className="h-3.5 w-3.5 shrink-0" style={{ color: "var(--warning)" }} />
          <span>
            <strong>{modelOverride.name}</strong> may not support image input.
            The image will be sent as text metadata instead.
          </span>
        </div>
      )}

      {/* Model selector + thinking controls + context indicator — above the input bar */}
      {!isElicitation && (
        <div className="mx-auto flex max-w-[672px] items-center gap-1.5 pb-1.5">
          <ModelSelector
            defaultProviderId={defaultProviderId}
            defaultModelName={defaultModelName}
            onChange={setModelOverride}
          />
          {/* Thinking toggle — only show when the selected model supports thinking */}
          {modelOverride?.supports_thinking && (
            <ThinkingToggle
              enabled={thinkingEnabled}
              effort={thinkingEffort}
              efforts={modelOverride.thinking_efforts || ["low", "medium", "high"]}
              onToggle={(enabled) => setThinkingEnabled(enabled)}
              onEffortChange={setThinkingEffort}
            />
          )}
          {contextTokens != null && maxContextTokens != null && maxContextTokens > 0 && (
            <ContextCircle
              contextTokens={contextTokens}
              maxContextTokens={maxContextTokens}
              compacted={compacted}
              breakdown={contextBreakdown}
            />
          )}
        </div>
      )}

      <div className="relative mx-auto flex max-w-[672px] items-end gap-2">
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
            accept="*/*"
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
                  label="File"
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

        {/* Slash command autocomplete */}
        {showSkillMenu && (
          <div
            className="absolute bottom-full left-0 mb-1 w-full max-w-md rounded-lg border shadow-lg overflow-hidden"
            style={{
              background: "var(--white)",
              borderColor: "var(--border)",
              maxHeight: "240px",
              overflowY: "auto",
            }}
          >
            {allFiltered.slice(0, 6).map((cmd, i) => (
              <button
                key={cmd.name}
                onClick={() => {
                  if ("isBuiltin" in cmd && cmd.isBuiltin) {
                    // Built-in commands execute immediately — no text after
                    setText(`/${cmd.name} `);
                    textareaRef.current?.focus();
                  } else {
                    const skill = cmd as SkillInfo;
                    const afterSlash = text.slice(slashMatch![0].length);
                    setText(`/${skill.name} ${afterSlash}`.trim() + " ");
                    textareaRef.current?.focus();
                  }
                }}
                className="flex w-full items-start gap-2 px-3 py-2 text-left transition"
                style={{
                  background: i === skillIndex ? "var(--surface)" : "none",
                  border: "none",
                  cursor: "pointer",
                }}
                onMouseEnter={() => setSkillIndex(i)}
              >
                {"isBuiltin" in cmd && cmd.isBuiltin ? (
                  <Wrench className="mt-0.5 h-3.5 w-3.5 shrink-0" style={{ color: "var(--color-secondary)" }} />
                ) : (
                  <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0" style={{ color: "var(--accent)" }} />
                )}
                <div className="min-w-0 flex-1">
                  <p className="font-mono text-[13px] font-medium text-[var(--ink)]">
                    /{cmd.name}
                  </p>
                  {cmd.description && (
                    <p className="text-[11px] text-[var(--ink-3)] truncate">
                      {cmd.description}
                    </p>
                  )}
                </div>
              </button>
            ))}
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

        {/* Send / Stop — stop button replaces send while a run is active */}
        {(() => {
          // Show stop button when a run is active (disabled && not elicitation)
          const isRunning = disabled && !isElicitation && onStop;
          if (isRunning) {
            return (
              <button
                onClick={onStop}
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[5px] border transition"
                style={{
                  background: "var(--danger, #dc2626)",
                  color: "var(--white)",
                  borderColor: "var(--danger, #dc2626)",
                  cursor: "pointer",
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.opacity = "0.85";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.opacity = "1";
                }}
                title="Stop run"
              >
                <Square className="h-3.5 w-3.5 fill-current" />
              </button>
            );
          }
          // Send button
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

      {/* Drag-and-drop overlay */}
      {isDragging && (
        <div
          className="absolute inset-0 z-50 flex items-center justify-center rounded-[inherit]"
          style={{
            background: "rgba(0, 0, 0, 0.05)",
            borderTop: "2px dashed var(--accent)",
            borderBottom: "2px dashed var(--accent)",
          }}
        >
          <div className="flex items-center gap-2 text-[14px] font-medium" style={{ color: "var(--accent)" }}>
            <Paperclip className="h-5 w-5" />
            Drop files to attach
          </div>
        </div>
      )}
    </div>
  );
});

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

function ContextCircle({
  contextTokens,
  maxContextTokens,
  compacted,
  breakdown,
}: {
  contextTokens: number;
  maxContextTokens: number;
  compacted?: boolean;
  breakdown?: { system_prompt: number; conversation: number; tools: number };
}) {
  const [showTooltip, setShowTooltip] = useState(false);
  const pct = Math.min(100, (contextTokens / maxContextTokens) * 100);
  const ratio = contextTokens / maxContextTokens;
  const isWarning = ratio > 0.7;
  const color = isWarning ? "var(--warning)" : "var(--brand-2)";
  const trackColor = "#E0DFDC";
  const radius = 7;
  const circumference = 2 * Math.PI * radius;
  const dashOffset = circumference - (pct / 100) * circumference;

  const sections = breakdown
    ? [
        { label: "System Prompt", tokens: breakdown.system_prompt, color: "var(--accent)" },
        { label: "Conversation", tokens: breakdown.conversation, color: "var(--brand-2)" },
        { label: "Tools", tokens: breakdown.tools, color: "var(--warning)" },
      ].filter((s) => s.tokens > 0)
    : [];

  return (
    <div
      className="relative shrink-0"
      onMouseEnter={() => setShowTooltip(true)}
      onMouseLeave={() => setShowTooltip(false)}
    >
      <div
        className="flex h-7 w-7 items-center justify-center rounded-full transition"
        style={{ cursor: "pointer" }}
        title="Context window usage"
      >
        <svg width="18" height="18" viewBox="0 0 18 18">
          <circle
            cx="9"
            cy="9"
            r={radius}
            fill="none"
            stroke={trackColor}
            strokeWidth="2"
          />
          <circle
            cx="9"
            cy="9"
            r={radius}
            fill="none"
            stroke={color}
            strokeWidth="2"
            strokeDasharray={circumference}
            strokeDashoffset={dashOffset}
            strokeLinecap="round"
            transform="rotate(-90 9 9)"
            style={{ transition: "stroke-dashoffset 0.3s ease" }}
          />
        </svg>
      </div>

      {showTooltip && (
        <div
          className="absolute bottom-full right-0 mb-1 z-50 w-60 rounded-lg border p-3 shadow-lg"
          style={{
            background: "var(--white)",
            borderColor: "var(--border)",
          }}
        >
          <div className="mb-2 flex items-center justify-between">
            <span className="text-[12px] font-semibold" style={{ color: "var(--ink)" }}>
              Context Window
            </span>
            <span className="text-[11px] tabular-nums" style={{ color: isWarning ? color : "var(--ink-2)" }}>
              {pct.toFixed(1)}%
            </span>
          </div>

          {/* Stacked bar showing section proportions */}
          {sections.length > 0 && (
            <div className="mb-2.5 flex h-2 w-full overflow-hidden rounded-full" style={{ background: "#E0DFDC" }}>
              {sections.map((s) => (
                <div
                  key={s.label}
                  className="h-full transition-all"
                  style={{
                    width: `${(s.tokens / maxContextTokens) * 100}%`,
                    background: s.color,
                  }}
                />
              ))}
            </div>
          )}

          {/* Per-section breakdown */}
          {sections.length > 0 ? (
            <div className="space-y-1.5 text-[11px]">
              {sections.map((s) => (
                <div key={s.label} className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5">
                    <div className="h-2 w-2 rounded-full" style={{ background: s.color }} />
                    <span style={{ color: "var(--ink-2)" }}>{s.label}</span>
                  </div>
                  <span className="tabular-nums" style={{ color: "var(--ink)" }}>
                    {s.tokens.toLocaleString()}
                  </span>
                </div>
              ))}
              <div className="mt-1.5 border-t pt-1.5" style={{ borderColor: "var(--border)" }}>
                <div className="flex items-center justify-between">
                  <span style={{ color: "var(--ink-2)" }}>Total Used</span>
                  <span className="tabular-nums font-medium" style={{ color: isWarning ? color : "var(--ink)" }}>
                    {contextTokens.toLocaleString()}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span style={{ color: "var(--ink-2)" }}>Max</span>
                  <span className="tabular-nums" style={{ color: "var(--ink-2)" }}>
                    {maxContextTokens.toLocaleString()}
                  </span>
                </div>
              </div>
            </div>
          ) : (
            <div className="space-y-1 text-[11px]" style={{ color: "var(--ink-2)" }}>
              <div className="flex justify-between">
                <span>Used</span>
                <span className="tabular-nums" style={{ color: isWarning ? color : "var(--ink)" }}>
                  {contextTokens.toLocaleString()} tokens
                </span>
              </div>
              <div className="flex justify-between">
                <span>Max</span>
                <span className="tabular-nums">{maxContextTokens.toLocaleString()} tokens</span>
              </div>
            </div>
          )}

          {compacted && (
            <div className="mt-2 rounded px-1.5 py-1 text-[10px]" style={{ background: "var(--surface)", color: "var(--ink-3)" }}>
              Context was compacted — older messages summarized
            </div>
          )}
          {isWarning && !compacted && (
            <div className="mt-2 text-[10px]" style={{ color }}>
              Approaching limit — type /compact to summarize
            </div>
          )}
        </div>
      )}
    </div>
  );
}


/** Thinking toggle + effort selector — shown when the selected model supports reasoning. */
function ThinkingToggle({
  enabled,
  effort,
  efforts,
  onToggle,
  onEffortChange,
}: {
  enabled: boolean | null;
  effort: string;
  efforts: string[];
  onToggle: (enabled: boolean) => void;
  onEffortChange: (effort: string) => void;
}) {
  const isOn = enabled === true;

  return (
    <div className="flex items-center gap-1">
      <button
        type="button"
        onClick={() => onToggle(!isOn)}
        className="flex items-center gap-1 rounded-[4px] border px-2 py-1 font-mono text-[11px] transition"
        style={{
          borderColor: isOn ? "var(--accent)" : "var(--border)",
          background: isOn ? "var(--surface)" : "transparent",
          color: isOn ? "var(--accent)" : "var(--ink-3)",
        }}
        title={isOn ? "Thinking enabled — click to disable" : "Enable thinking/reasoning"}
      >
        <Brain className="h-3 w-3" />
        <span>Think</span>
      </button>
      {isOn && efforts.length > 1 && (
        <select
          value={effort}
          onChange={(e) => onEffortChange(e.target.value)}
          className="rounded-[4px] border px-1.5 py-1 font-mono text-[11px] outline-none"
          style={{
            borderColor: "var(--border)",
            background: "var(--surface)",
            color: "var(--ink-2)",
          }}
        >
          {efforts.map((e) => (
            <option key={e} value={e}>{e}</option>
          ))}
        </select>
      )}
    </div>
  );
}
