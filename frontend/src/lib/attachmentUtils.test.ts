import { describe, expect, it } from "vitest";
import {
  attachmentKind,
  fileHash,
  formatAttachmentSize,
  moveItem,
} from "./attachmentUtils";

describe("fileHash", () => {
  it("produces a stable sha256 hex of the bytes", async () => {
    const file = new File(["hello"], "a.txt", { type: "text/plain" });
    const hash = await fileHash(file);
    // sha256("hello") — well-known vector
    expect(hash).toBe(
      "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
    );
  });

  it("distinguishes identical names with different bytes", async () => {
    const a = new File(["x"], "same.png");
    const b = new File(["y"], "same.png");
    expect(await fileHash(a)).not.toBe(await fileHash(b));
  });
});

describe("attachmentKind", () => {
  it("maps by mime first, then extension", () => {
    expect(attachmentKind("shot.png", "image/png")).toBe("image");
    expect(attachmentKind("clip.mp4", "video/mp4")).toBe("video");
    expect(attachmentKind("song.mp3", "audio/mpeg")).toBe("audio");
    expect(attachmentKind("doc.pdf", "application/pdf")).toBe("pdf");
    expect(attachmentKind("doc.docx", "application/octet-stream")).toBe("document");
    expect(attachmentKind("deck.pptx", "application/octet-stream")).toBe("slides");
    expect(attachmentKind("book.xlsx", "application/octet-stream")).toBe("workbook");
    expect(attachmentKind("data.csv", "text/csv")).toBe("table");
    expect(attachmentKind("notes.md", "text/markdown")).toBe("markdown");
    expect(attachmentKind("blob.bin", "application/octet-stream")).toBe("file");
    expect(attachmentKind("readme.txt", "text/plain")).toBe("text");
  });
});

describe("moveItem", () => {
  it("moves within bounds and is a no-op at the edges", () => {
    expect(moveItem([1, 2, 3], 0, 1)).toEqual([2, 1, 3]);
    expect(moveItem([1, 2, 3], 2, 1)).toEqual([1, 2, 3]);
    expect(moveItem([1, 2, 3], 0, -1)).toEqual([1, 2, 3]);
    expect(moveItem([1, 2, 3], 1, -1)).toEqual([2, 1, 3]);
  });
});

describe("formatAttachmentSize", () => {
  it("formats human sizes", () => {
    expect(formatAttachmentSize(512)).toBe("512 B");
    expect(formatAttachmentSize(2048)).toBe("2.0 KB");
    expect(formatAttachmentSize(5 * 1024 * 1024)).toBe("5.0 MB");
  });
});
