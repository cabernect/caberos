import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import type { ComponentProps } from "react";
import { createRef } from "react";
import { ChatInputBar, type ChatInputBarHandle } from "./ChatInputBar";
import { ThemeProvider } from "@/lib/theme";

vi.stubGlobal("matchMedia", (q: string) => ({
  matches: false, media: q, addEventListener: () => {}, removeEventListener: () => {},
  addListener: () => {}, removeListener: () => {}, onchange: null, dispatchEvent: () => false,
}));
vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
vi.mock("@/lib/confirmHook", () => ({
  useConfirm: () => ({ confirm: vi.fn(async () => true), toast: vi.fn() }),
}));
vi.mock("@/lib/api", async (orig) => {
  const real = await orig<typeof import("@/lib/api")>();
  return {
    ...real,
    api: {
      ...real.api,
      listAvailableSkills: vi.fn(async () => []),
      previewAttachment: vi.fn(async () => ({ thumb_png: null })),
    },
  };
});

type OnSend = ComponentProps<typeof ChatInputBar>["onSend"];

function mount(props: Partial<ComponentProps<typeof ChatInputBar>> = {}) {
  const ref = createRef<ChatInputBarHandle>();
  render(
    <ThemeProvider>
      <ChatInputBar
        ref={ref}
        agentId="a1"
        defaultProviderId="p1"
        defaultModelName="m1"
        onSend={vi.fn(async () => true)}
        {...props}
      />
    </ThemeProvider>,
  );
  return ref;
}

// jsdom File lacks .text() — attach per-file instead of polluting the
// global prototype.
function readable(f: File): File {
  Object.defineProperty(f, "text", {
    value: function (this: File) {
      return new Promise<string>((res, rej) => {
        const r = new FileReader();
        r.onload = () => res(r.result as string);
        r.onerror = () => rej(r.error);
        r.readAsText(this);
      });
    },
  });
  return f;
}

const sendButton = () => screen.getByTitle(/Send/) as HTMLButtonElement;

const stage = async (ref: React.RefObject<ChatInputBarHandle | null>, files: File[]) => {
  await act(async () => {
    await ref.current!.addFiles(files);
  });
};
const textFile = (name: string, content = "hello") =>
  readable(new File([content], name, { type: "text/plain" }));

describe("ChatInputBar attachment-only sends", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.restoreAllMocks());

  it("attachment-only enables Send and delivers empty text + attachment payload", async () => {
    const onSend = vi.fn(async () => true);
    const ref = mount({ onSend });
    await stage(ref, [textFile("notes.txt")]);
    expect(sendButton().disabled).toBe(false);
    fireEvent.click(sendButton());
    await vi.waitFor(() => expect(onSend).toHaveBeenCalled());
    const [text, , , attachments] = onSend.mock.calls[0] as unknown as Parameters<NonNullable<OnSend>>;
    expect(text).toBe("");
    expect(attachments![0].filename).toBe("notes.txt");
    expect(attachments![0].data).toBe("hello");
    // tray cleared on success
    await vi.waitFor(() => expect(sendButton().disabled).toBe(true));
  });

  it("attachment-only send via Enter", async () => {
    const onSend = vi.fn(async () => true);
    const ref = mount({ onSend });
    await stage(ref, [textFile("a.txt")]);
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter", shiftKey: false });
    await vi.waitFor(() => expect(onSend).toHaveBeenCalled());
    expect((onSend.mock.calls[0] as unknown as Parameters<NonNullable<OnSend>>)[0]).toBe("");
  });

  it("failed send keeps the attachment", async () => {
    const onSend = vi.fn(async () => false);
    const ref = mount({ onSend });
    await stage(ref, [textFile("keep.txt")]);
    fireEvent.click(sendButton());
    await vi.waitFor(() => expect(onSend).toHaveBeenCalled());
    expect(sendButton().disabled).toBe(false);
  });

  it("Send stays disabled while a file is still processing", async () => {
    const onSend = vi.fn(async () => true);
    let resolveRead: ((v: string) => void) | null = null;
    const slow = new File(["x"], "slow.txt", { type: "text/plain" });
    Object.defineProperty(slow, "text", {
      value: () => new Promise<string>((r) => { resolveRead = r; }),
    });
    const ref = mount({ onSend });
    const pending = ref.current!.addFiles([slow]);  // un-awaited on purpose
    await act(async () => { /* flush staging state */ });
    // bytes still being read — Send stays disabled until the payload lands
    await vi.waitFor(() => expect(resolveRead).not.toBeNull());
    expect(sendButton().disabled).toBe(true);
    resolveRead!("slow-body");
    await act(async () => { await pending; });
    await vi.waitFor(() => expect(sendButton().disabled).toBe(false));
  });

  it("disabled composer blocks attachment-only send", async () => {
    const onSend = vi.fn(async () => true);
    const ref = mount({ onSend, disabled: true });
    await stage(ref, [textFile("d.txt")]);
    expect(sendButton().disabled).toBe(true);
    expect(onSend).not.toHaveBeenCalled();
  });

  it("no attachment and no text leaves Send disabled", () => {
    mount();
    expect(sendButton().disabled).toBe(true);
  });

  it("text-only still works", async () => {
    const onSend = vi.fn(async () => true);
    mount({ onSend });
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "hello" } });
    fireEvent.click(sendButton());
    await vi.waitFor(() => expect(onSend).toHaveBeenCalled());
    expect((onSend.mock.calls[0] as unknown as Parameters<NonNullable<OnSend>>)[0]).toBe("hello");
  });
});


describe("ChatInputBar failed reads", () => {
  it("a file that can't be read never stages a card and Send stays off", async () => {
    const onSend = vi.fn(async () => true);
    const ref = mount({ onSend });
    const bad = new File(["x"], "broken.txt", { type: "text/plain" });
    Object.defineProperty(bad, "text", {
      value: () => Promise.reject(new Error("read failed")),
    });
    await act(async () => { await ref.current!.addFiles([bad]); });
    expect(sendButton().disabled).toBe(true);
    expect(onSend).not.toHaveBeenCalled();
    // tray note explains, no failed card
    await vi.waitFor(() =>
      expect(document.body.textContent).toContain("Could not read")
    );
    // the only mention is the error note — no staged card exists
    expect(document.body.textContent!.match(/broken\.txt/g)).toHaveLength(1);
  });
});
