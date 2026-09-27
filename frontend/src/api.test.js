import { afterEach, describe, expect, it, vi } from "vitest";
import api from "./api";

const reply = (status, body) =>
  vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status }));

afterEach(() => vi.unstubAllGlobals());

describe("api", () => {
  it("sends the board id and query params, and resolves to { data }", async () => {
    const fetch = reply(200, { notes: [1] });
    vi.stubGlobal("fetch", fetch);
    const r = await api.get("/api/notes/", { params: { studentID: "s 1" } });
    expect(r.data).toEqual({ notes: [1] });
    const [url, init] = fetch.mock.calls[0];
    expect(url).toBe("/api/notes/?studentID=s+1");
    expect(init.headers["X-Board-Id"]).toBeTruthy();
  });

  it("posts JSON bodies", async () => {
    const fetch = reply(200, {});
    vi.stubGlobal("fetch", fetch);
    await api.post("/api/picked/", { studentID: "s1" });
    expect(fetch.mock.calls[0][1]).toMatchObject({
      method: "POST",
      body: '{"studentID":"s1"}',
    });
  });

  it("rejects non-2xx with err.response and raises the Turnstile event on its 403", async () => {
    vi.stubGlobal("fetch", reply(403, { error: "turnstile_required" }));
    const seen = vi.fn();
    window.addEventListener("turnstile:required", seen);
    const err = await api.get("/api/tracked/").catch((e) => e);
    window.removeEventListener("turnstile:required", seen);
    expect(err.response).toEqual({ status: 403, data: { error: "turnstile_required" } });
    expect(seen).toHaveBeenCalledOnce();
  });
});
