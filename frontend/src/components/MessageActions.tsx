import { useEffect, useRef, useState } from "react";
import { Check, Copy, Loader2, Square, Volume2 } from "lucide-react";
import { getSpeechStatus, synthesizeSpeech } from "@/lib/api";

// Cheap client-side mirror of backend/speech/renderer.has_speakable_text:
// strip fenced code, tables and images — anything left means there's prose
// worth a speaker button. The backend re-validates authoritatively.

// One playback at a time across all messages — a newer request claims a
// fresh generation; a superseded or unmounted request never reaches
// playback, so overlapping synthesis can never double up.
let _activeAudio: { stop: () => void } | null = null;
let _playbackToken = 0;

function hasProse(markdown: string): boolean {
  const stripped = markdown
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/~~~[\s\S]*?~~~/g, " ")
    .replace(/```[\s\S]*$/g, " ")
    .replace(/!\[[^\]]*\]\([^)]*\)/g, " ")
    .replace(/^\s*\|.*$/gm, " ");
  return stripped.trim().length > 0;
}

type SpeechState = "idle" | "generating" | "playing" | "failed";

function SpeakerButton({ messageId }: { messageId: string }) {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [state, setState] = useState<SpeechState>("idle");
  const [error, setError] = useState("");
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const urlRef = useRef<string | null>(null);
  const liveRef = useRef(true);

  useEffect(() => {
    liveRef.current = true;
    let live = true;
    getSpeechStatus()
      .then((s) => live && setEnabled(s.tts.ready))
      .catch(() => live && setEnabled(false));
    return () => {
      live = false;
      liveRef.current = false;
      stopPlayback();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const stopPlayback = () => {
    _playbackToken += 1; // invalidate any pending synthesis claim
    audioRef.current?.pause();
    audioRef.current = null;
    if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    urlRef.current = null;
    if (_activeAudio) _activeAudio = null;
    if (liveRef.current) setState((s) => (s === "playing" ? "idle" : s));
  };

  const speak = async () => {
    if (state === "playing") {
      stopPlayback();
      return;
    }
    _activeAudio?.stop();
    const token = ++_playbackToken;
    setError("");
    setState("generating");
    try {
      const blob = await synthesizeSpeech(messageId);
      if (token !== _playbackToken) {
        // Superseded by a newer request or invalidated on unmount —
        // a stale blob never reaches playback.
        if (liveRef.current) setState("idle");
        return;
      }
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      urlRef.current = url;
      audioRef.current = audio;
      _activeAudio = { stop: stopPlayback };
      audio.onended = () => stopPlayback();
      audio.onerror = () => {
        setError("Playback failed");
        setState("failed");
        stopPlayback();
      };
      await audio.play();
      setState("playing");
    } catch (e) {
      if (token !== _playbackToken) {
        // Superseded — release this button's spinner only; the newer
        // playback is untouched.
        if (liveRef.current) setState("idle");
        return;
      }
      if (!liveRef.current) return;
      setError(e instanceof Error ? e.message : "Speech failed");
      setState("failed");
    }
  };

  if (enabled !== true) return null;
  const label =
    state === "generating"
      ? "Generating speech…"
      : state === "playing"
        ? "Stop reading"
        : "Read aloud";
  return (
    <>
      <button
        type="button"
        onClick={speak}
        disabled={state === "generating"}
        aria-label={label}
        title={label}
        className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-md text-[var(--ink-3)] transition-colors hover:bg-[var(--hover)] hover:text-[var(--ink)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)] disabled:cursor-wait"
      >
        {state === "generating" ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
        ) : state === "playing" ? (
          <Square className="h-3.5 w-3.5" />
        ) : (
          <Volume2 className="h-3.5 w-3.5" />
        )}
      </button>
      <span
        role="status"
        className={state === "failed" ? "text-[12px] text-[var(--ink-2)]" : "sr-only"}
      >
        {state === "generating" ? "Generating…" : state === "failed" ? error : ""}
      </span>
    </>
  );
}

export function MessageActions({
  content,
  messageId,
}: {
  content: string;
  messageId?: string;
}) {
  const [status, setStatus] = useState<"idle" | "copying" | "copied" | "error">("idle");
  const resetTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    if (resetTimer.current) clearTimeout(resetTimer.current);
  }, []);

  if (!content.trim()) return null;

  const copyMessage = async () => {
    if (resetTimer.current) clearTimeout(resetTimer.current);
    setStatus("copying");
    try {
      await navigator.clipboard.writeText(content);
      setStatus("copied");
      resetTimer.current = setTimeout(() => setStatus("idle"), 2000);
    } catch {
      setStatus("error");
    }
  };

  const label = status === "copied" ? "Copied" : "Copy message";
  return (
    <div className="flex items-center gap-1">
      <button
        type="button"
        onClick={copyMessage}
        disabled={status === "copying"}
        aria-label={label}
        title={label}
        className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-md text-[var(--ink-3)] transition-colors hover:bg-[var(--hover)] hover:text-[var(--ink)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)] disabled:cursor-wait"
      >
        {status === "copied" ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
      </button>
      {messageId && hasProse(content) ? <SpeakerButton messageId={messageId} /> : null}
      <span role="status" className={status === "error" ? "text-[12px] text-[var(--ink-2)]" : "sr-only"}>
        {status === "copied" ? "Message copied" : status === "error" ? "Couldn't copy. Try again or select the text manually." : ""}
      </span>
    </div>
  );
}
