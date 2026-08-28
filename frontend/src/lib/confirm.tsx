import { useState, useCallback, type ReactNode } from "react";
import { ConfirmContext } from "./confirmContext";
import type { ConfirmOptions } from "./confirmTypes";

/**
 * Tauri's webview does not support window.confirm() or window.alert().
 * These helpers provide inline alternatives that work in both web and desktop.
 */

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [dialog, setDialog] = useState<(ConfirmOptions & { resolve: (v: boolean) => void }) | null>(null);
  const [toastMsg, setToastMsg] = useState<string | null>(null);

  const confirm = useCallback((opts: ConfirmOptions) => {
    return new Promise<boolean>((resolve) => {
      setDialog({ ...opts, resolve });
    });
  }, []);

  const toast = useCallback((message: string) => {
    setToastMsg(message);
    setTimeout(() => setToastMsg(null), 3000);
  }, []);

  return (
    <ConfirmContext.Provider value={{ confirm, toast }}>
      {children}
      {dialog && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center"
          style={{ background: "rgba(0,0,0,0.3)" }}
          onClick={() => {
            dialog.resolve(false);
            setDialog(null);
          }}
        >
          <div
            className="w-full max-w-sm rounded-lg border p-5 shadow-2xl"
            style={{ background: "var(--white)", borderColor: "var(--border)" }}
            onClick={(e) => e.stopPropagation()}
          >
            {dialog.title && (
              <h3 className="mb-2 text-[15px] font-semibold text-[var(--ink)]">
                {dialog.title}
              </h3>
            )}
            <p className="mb-4 text-[13px] text-[var(--ink-2)]">{dialog.message}</p>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => {
                  dialog.resolve(false);
                  setDialog(null);
                }}
                className="rounded-md px-3 py-1.5 text-[12px] font-medium transition"
                style={{ border: "1px solid var(--border)", background: "none", color: "var(--ink-2)", cursor: "pointer" }}
              >
                {dialog.cancelLabel || "Cancel"}
              </button>
              <button
                onClick={() => {
                  dialog.resolve(true);
                  setDialog(null);
                }}
                className="rounded-md px-3 py-1.5 text-[12px] font-medium text-white transition"
                style={{
                  background: dialog.danger ? "var(--danger)" : "var(--accent)",
                  cursor: "pointer",
                }}
              >
                {dialog.confirmLabel || "Confirm"}
              </button>
            </div>
          </div>
        </div>
      )}
      {toastMsg && (
        <div
          className="fixed bottom-6 left-1/2 z-[100] -translate-x-1/2 rounded-lg px-4 py-2.5 text-[13px] shadow-lg"
          style={{ background: "var(--ink)", color: "var(--white)" }}
        >
          {toastMsg}
        </div>
      )}
    </ConfirmContext.Provider>
  );
}
