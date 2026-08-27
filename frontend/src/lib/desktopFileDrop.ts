import { useEffect, useRef } from "react";

interface DroppedFile {
  name: string;
  bytes: number[];
}

interface DesktopFileDropOptions {
  onFiles: (files: File[]) => void | Promise<void>;
  onDraggingChange?: (dragging: boolean) => void;
  onError?: (error: unknown) => void;
}

function mimeTypeFor(name: string): string {
  const extension = name.toLowerCase().split(".").pop();
  return {
    md: "text/markdown",
    markdown: "text/markdown",
    txt: "text/plain",
    json: "application/json",
    pdf: "application/pdf",
    docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    png: "image/png",
    jpg: "image/jpeg",
    jpeg: "image/jpeg",
    gif: "image/gif",
    webp: "image/webp",
  }[extension || ""] || "application/octet-stream";
}

export function useDesktopFileDrop({ onFiles, onDraggingChange, onError }: DesktopFileDropOptions) {
  const callbacks = useRef({ onFiles, onDraggingChange, onError });
  callbacks.current = { onFiles, onDraggingChange, onError };

  useEffect(() => {
    if (typeof window === "undefined" || !("__TAURI_INTERNALS__" in window)) return;

    let active = true;
    let unlisten: (() => void) | undefined;
    void (async () => {
      try {
        const { getCurrentWebviewWindow } = await import("@tauri-apps/api/webviewWindow");
        unlisten = await getCurrentWebviewWindow().onDragDropEvent((event) => {
          if (!active) return;
          if (event.payload.type === "enter" || event.payload.type === "over") {
            callbacks.current.onDraggingChange?.(true);
            return;
          }
          if (event.payload.type === "leave") {
            callbacks.current.onDraggingChange?.(false);
            return;
          }
          if (event.payload.type !== "drop") return;
          callbacks.current.onDraggingChange?.(false);
          const paths = event.payload.paths;
          void (async () => {
            try {
              const { invoke } = await import("@tauri-apps/api/core");
              const dropped = await Promise.all(
                paths.map((path) => invoke<DroppedFile>("read_dropped_file", { path })),
              );
              const files = dropped.map(({ name, bytes }) => new File([new Uint8Array(bytes)], name, { type: mimeTypeFor(name) }));
              if (files.length > 0) await callbacks.current.onFiles(files);
            } catch (error) {
              callbacks.current.onError?.(error);
            }
          })();
        });
      } catch (error) {
        callbacks.current.onError?.(error);
      }
    })();

    return () => {
      active = false;
      unlisten?.();
    };
  }, []);
}
