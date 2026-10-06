// Tests for the API seam in api.ts: the silent token refresh on 401, error
// messages, and how post analysis decides between a link and pasted text.
import { beforeEach, describe, expect, it, vi } from "vitest";
import { analyzePost, getKpis } from "./api";

type Call = [string, RequestInit | undefined];

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

const urls = () => (fetchMock.mock.calls as Call[]).map(([url]) => url);

describe("request", () => {
  it("returns the JSON body on success", async () => {
    fetchMock.mockResolvedValueOnce(json(200, [{ id: "mentions" }]));
    await expect(getKpis()).resolves.toEqual([{ id: "mentions" }]);
    expect(urls()).toEqual(["/api/kpis"]);
  });

  it("refreshes the session once on 401 and retries the request", async () => {
    fetchMock
      .mockResolvedValueOnce(json(401, {}))              // expired access token
      .mockResolvedValueOnce(json(200, { ok: true }))    // /api/auth/refresh
      .mockResolvedValueOnce(json(200, [{ id: "reach" }])); // retry
    await expect(getKpis()).resolves.toEqual([{ id: "reach" }]);
    expect(urls()).toEqual(["/api/kpis", "/api/auth/refresh", "/api/kpis"]);
  });

  it("shares one refresh between requests that fail at the same time", async () => {
    let finishRefresh!: (r: Response) => void;
    fetchMock.mockImplementation((url: string) => {
      if (url === "/api/auth/refresh") return new Promise<Response>((r) => { finishRefresh = r; });
      const retried = urls().filter((u) => u === url).length > 1;
      return Promise.resolve(retried ? json(200, []) : json(401, {}));
    });

    const both = Promise.all([getKpis(), getKpis()]);
    await vi.waitFor(() => expect(finishRefresh).toBeDefined());
    finishRefresh(json(200, { ok: true }));
    await both;

    expect(urls().filter((u) => u === "/api/auth/refresh")).toHaveLength(1);
  });

  it("gives up when the refresh fails", async () => {
    fetchMock
      .mockResolvedValueOnce(json(401, {}))
      .mockResolvedValueOnce(json(401, {}));
    await expect(getKpis()).rejects.toThrow("GET /kpis failed: 401");
  });

  it("uses the API's error message when there is one", async () => {
    fetchMock.mockResolvedValueOnce(json(400, { detail: "Bad range" }));
    await expect(getKpis()).rejects.toThrow("Bad range");
  });
});

describe("analyzePost", () => {
  const body = () => JSON.parse(String((fetchMock.mock.calls as Call[])[0][1]?.body));

  it("sends a link as url", async () => {
    fetchMock.mockResolvedValueOnce(json(200, {}));
    await analyzePost("  https://x.com/a/status/1 ");
    expect(body()).toEqual({ url: "https://x.com/a/status/1" });
  });

  it("sends anything else as text", async () => {
    fetchMock.mockResolvedValueOnce(json(200, {}));
    await analyzePost("Got sick after the Berry batch");
    expect(body()).toEqual({ text: "Got sick after the Berry batch" });
  });
});
