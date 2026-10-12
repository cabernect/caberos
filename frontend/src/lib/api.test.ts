import { describe, expect, it, vi, beforeEach } from "vitest";
import { api } from "./api";

describe("api query serialization", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({}), { status: 200 })),
    );
  });

  function url(): string {
    return (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0];
  }

  it("listRuns serializes false/0 and every filter", async () => {
    await api.listRuns({
      is_test: false,
      retrieval_degraded: false,
      offset: 0,
      limit: 1,
      provider_id: "p1",
      model: "m1",
      purpose: "reasoning",
      kind: "chat",
      schedule_id: "s1",
      channel: "telegram",
      capability: "terminal",
      tool_status: "denied",
      browser_profile: "work",
      artifact_format: "docx",
      retrieval_mode: "hybrid",
      effect: "write",
      since: "2024-01-01T00:00:00",
      until: "2024-02-01T00:00:00",
      agent_id: "a1",
      status: "failed",
      trigger: "scheduler",
    });
    const u = url();
    for (const [k, v] of [
      ["is_test", "false"],
      ["retrieval_degraded", "false"],
      ["offset", "0"],
      ["limit", "1"],
      ["provider_id", "p1"],
      ["model", "m1"],
      ["purpose", "reasoning"],
      ["kind", "chat"],
      ["schedule_id", "s1"],
      ["channel", "telegram"],
      ["capability", "terminal"],
      ["tool_status", "denied"],
      ["browser_profile", "work"],
      ["artifact_format", "docx"],
      ["retrieval_mode", "hybrid"],
      ["effect", "write"],
      ["agent_id", "a1"],
      ["status", "failed"],
      ["trigger", "scheduler"],
    ]) {
      expect(new URL(u, "http://x").searchParams.get(k)).toBe(v);
    }
  });

  it("listRuns omits empty-string filters but keeps explicit false", async () => {
    await api.listRuns({ provider_id: "", is_test: false });
    const params = new URL(url(), "http://x").searchParams;
    expect(params.has("provider_id")).toBe(false);
    expect(params.get("is_test")).toBe("false");
  });

  it("getSpend stays agent-scoped by default", async () => {
    await api.getSpend(7, "a1");
    const u = url();
    expect(u).not.toContain("scope=platform");
    expect(u).toContain("days=7");
    expect(u).toContain("agent_id=a1");
  });

  it("getPlatformSpend is explicitly scope=platform", async () => {
    await api.getPlatformSpend({ days: 3, provider_id: "p1", kind: "chat" });
    const params = new URL(url(), "http://x").searchParams;
    expect(params.get("scope")).toBe("platform");
    expect(params.get("provider_id")).toBe("p1");
    expect(params.get("kind")).toBe("chat");
  });

  it("listAudit carries the new filters", async () => {
    await api.listAudit({
      outcome: "denied",
      call_id: "c1",
      sub_agent_id: "s1",
      since: "2024-01-01",
      until: "2024-02-01",
    });
    const params = new URL(url(), "http://x").searchParams;
    expect(params.get("outcome")).toBe("denied");
    expect(params.get("call_id")).toBe("c1");
    expect(params.get("sub_agent_id")).toBe("s1");
  });
});

function sseResponse(body: string): Response {
  return new Response(body, {
    status: 200,
    headers: { "content-type": "text/event-stream" },
  });
}

describe("streamNotifications SSE parsing", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: true, json: async () => ({ v: 1 }) })),
    );
  });

  it("hello fires onConnected once; invalidation fires onInboxChanged; notification yields", async () => {
    const frames = [
      `data: {"type":"hello"}\n\n`,
      `: keepalive\n\n`,
      `data: {"type":"inbox_changed"}\n\n`,
      `data: {"type":"notification","notification":{"id":"n1","notification_type":"x","severity":"info","title":"t","message":"m","action_path":null,"entity_id":null,"entity_type":null,"agent_id":null,"agent_name":null,"event_id":null,"read":false,"created_at":"2026-01-01T00:00:00Z"}}\n\n`,
      `data: {"type":"inbox_changed"}\r\n\r\n`, // CRLF frame
    ].join("");
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      sseResponse(frames),
    );
    const connected = vi.fn();
    const changed = vi.fn();
    const seen: string[] = [];
    for await (const n of api.streamNotifications(
      undefined,
      connected,
      changed,
    )) {
      seen.push(n.id);
    }
    expect(connected).toHaveBeenCalledTimes(1);
    expect(changed).toHaveBeenCalledTimes(2);
    expect(seen).toEqual(["n1"]);
  });

  it("keepalive-only stream yields nothing and invokes no callbacks", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      sseResponse(`: keepalive\n\n: keepalive\n\n`),
    );
    const connected = vi.fn();
    let count = 0;
    for await (const _n of api.streamNotifications(undefined, connected)) {
      count++;
    }
    expect(count).toBe(0);
    expect(connected).not.toHaveBeenCalled();
  });
});

it("duplicate hello fires onConnected once; split frames parse correctly", async () => {
  const frames =
    `data: {"type":"hello"}\n\ndata: {"type":"hel` + `lo"}\r\n\r\n: ka\n\n`;
  (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
    new Response(frames, { status: 200 }),
  );
  const connected = vi.fn();
  let count = 0;
  for await (const _n of api.streamNotifications(undefined, connected)) {
    count++;
  }
  expect(connected).toHaveBeenCalledTimes(1);
  expect(count).toBe(0);
});

it("reader is released when the stream ends", async () => {
  const cancel = vi.fn();
  const releaseLock = vi.fn();
  (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
    ok: true,
    body: {
      getReader: () => ({
        read: vi
          .fn()
          .mockResolvedValueOnce({
            done: false,
            value: new TextEncoder().encode('data: {"type":"hello"}\n\n'),
          })
          .mockResolvedValueOnce({ done: true, value: undefined }),
        cancel,
        releaseLock,
      }),
    },
  });
  const seen = api.streamNotifications();
  for await (const _n of seen) {
    void _n;
  }
  expect(cancel).toHaveBeenCalled();
  expect(releaseLock).toHaveBeenCalled();
});
