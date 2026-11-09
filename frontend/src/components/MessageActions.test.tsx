import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { getSpeechStatus, synthesizeSpeech } from "@/lib/api";
import { MessageActions } from "./MessageActions";

vi.mock("@/lib/api", async (orig) => {
  const real = await orig<typeof import("@/lib/api")>();
  return {
    ...real,
    getSpeechStatus: vi.fn(),
    synthesizeSpeech: vi.fn(),
  };
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function mockClipboard(writeText = vi.fn().mockResolvedValue(undefined)) {
  vi.stubGlobal("navigator", { clipboard: { writeText } });
  return writeText;
}

describe("MessageActions", () => {
  it("copies the entire original reply, including Markdown, code, and links", async () => {
    const writeText = mockClipboard();
    const content = "# Answer\n\n**Details**\n\n```ts\nconst n = 1;\n```\n\n[Image](artifacts/image.png)\n\nLast paragraph.";
    render(<MessageActions content={content} />);

    fireEvent.click(screen.getByRole("button", { name: "Copy message" }));

    expect(writeText).toHaveBeenCalledWith(content);
    await screen.findByRole("button", { name: "Copied" });
    expect(screen.getByRole("status").textContent).toBe("Message copied");
  });

  it("resets success feedback so the message can be copied again", async () => {
    vi.useFakeTimers();
    mockClipboard();
    render(<MessageActions content="Reply" />);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Copy message" }));
    });
    expect(screen.getByRole("button", { name: "Copied" })).toBeTruthy();
    act(() => vi.advanceTimersByTime(2000));
    expect(screen.getByRole("button", { name: "Copy message" })).toBeTruthy();
  });

  it("copies user input exactly, preserving whitespace and line breaks", async () => {
    const writeText = mockClipboard();
    const content = "  Please edit this:\n\nfirst line\n  indented line\n";
    render(<MessageActions content={content} />);
    fireEvent.click(screen.getByRole("button", { name: "Copy message" }));
    await screen.findByRole("button", { name: "Copied" });
    expect(writeText).toHaveBeenCalledWith(content);
  });

  it("reports clipboard denial without falsely claiming success and allows retry", async () => {
    const writeText = mockClipboard(vi.fn().mockRejectedValue(new Error("Denied")));
    render(<MessageActions content="Reply" />);
    fireEvent.click(screen.getByRole("button", { name: "Copy message" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toContain("Couldn't copy"));
    expect(screen.queryByRole("button", { name: "Copied" })).toBeNull();

    writeText.mockResolvedValue(undefined);
    fireEvent.click(screen.getByRole("button", { name: "Copy message" }));
    await screen.findByRole("button", { name: "Copied" });
  });

  it("handles an unavailable clipboard API", async () => {
    vi.stubGlobal("navigator", {});
    render(<MessageActions content="Reply" />);
    fireEvent.click(screen.getByRole("button", { name: "Copy message" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toContain("Couldn't copy"));
  });

  it("does not offer copying for an empty reply", () => {
    render(<MessageActions content={" \n "} />);
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("SpeakerButton", () => {
  function stubAudio() {
    const playMock = vi.fn().mockResolvedValue(undefined);
    const audioCtor = vi.fn();
    class FakeAudio {
      play = playMock;
      pause = vi.fn();
      onended: (() => void) | null = null;
      onerror: (() => void) | null = null;
      constructor(url: string) {
        audioCtor(url);
      }
    }
    vi.stubGlobal("Audio", FakeAudio);
    URL.createObjectURL ??= vi.fn(() => "blob:mock");
    URL.revokeObjectURL ??= vi.fn();
    return { playMock, audioCtor };
  }

  function speechReady() {
    vi.mocked(getSpeechStatus).mockResolvedValue({
      stt: { ready: false },
      tts: { ready: true },
    } as Awaited<ReturnType<typeof getSpeechStatus>>);
  }

  it("a superseded read-aloud request never reaches playback", async () => {
    speechReady();
    const { playMock, audioCtor } = stubAudio();
    let resolveFirst!: (b: Blob) => void;
    vi.mocked(synthesizeSpeech)
      .mockImplementationOnce(() => new Promise<Blob>((r) => (resolveFirst = r)))
      .mockResolvedValueOnce(new Blob(["b"]));

    render(
      <>
        <MessageActions content="first" messageId="m1" />
        <MessageActions content="second" messageId="m2" />
      </>,
    );
    const buttons = await screen.findAllByRole("button", { name: "Read aloud" });
    fireEvent.click(buttons[0]); // pending
    fireEvent.click(buttons[1]); // supersedes, resolves, plays
    await waitFor(() => expect(playMock).toHaveBeenCalledTimes(1));

    await act(async () => resolveFirst(new Blob(["a"])));
    // The stale claim resolves late — it never creates audio or double-plays.
    expect(playMock).toHaveBeenCalledTimes(1);
    expect(audioCtor).toHaveBeenCalledTimes(1);
    // …and its button settles back to idle, not stuck on "Generating".
    expect(screen.getAllByRole("button", { name: "Read aloud" })).toHaveLength(1);
  });

  it("a superseded request that later rejects still releases its button", async () => {
    speechReady();
    const { playMock } = stubAudio();
    let rejectFirst!: (e: Error) => void;
    vi.mocked(synthesizeSpeech)
      .mockImplementationOnce(() => new Promise<Blob>((_r, rej) => (rejectFirst = rej)))
      .mockResolvedValueOnce(new Blob(["b"]));

    render(
      <>
        <MessageActions content="first" messageId="m1" />
        <MessageActions content="second" messageId="m2" />
      </>,
    );
    const buttons = await screen.findAllByRole("button", { name: "Read aloud" });
    fireEvent.click(buttons[0]); // pending
    fireEvent.click(buttons[1]); // supersedes, plays
    await waitFor(() => expect(playMock).toHaveBeenCalledTimes(1));

    await act(async () => rejectFirst(new Error("synthesis blew up")));
    // The stale failure settles its own button to idle — never stuck on
    // "Generating" — while the newer playback keeps playing untouched.
    expect(screen.getAllByRole("button", { name: "Read aloud" })).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Stop reading" })).toBeTruthy();
  });

  it("a pending read-aloud request never plays after unmount", async () => {
    speechReady();
    const { playMock, audioCtor } = stubAudio();
    let resolveReq!: (b: Blob) => void;
    vi.mocked(synthesizeSpeech).mockImplementation(
      () => new Promise<Blob>((r) => (resolveReq = r)),
    );

    const { unmount } = render(<MessageActions content="hi" messageId="m1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Read aloud" }));
    unmount();

    await act(async () => resolveReq(new Blob(["a"])));
    expect(audioCtor).not.toHaveBeenCalled();
    expect(playMock).not.toHaveBeenCalled();
  });
});
