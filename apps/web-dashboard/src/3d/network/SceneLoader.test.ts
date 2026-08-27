import {afterEach, describe, expect, it, vi} from "vitest";

vi.mock("../scene/types", () => ({assertStaticScene: vi.fn()}));

import {loadStaticScene} from "./SceneLoader";

describe("static scene loading", () => {
  afterEach(() => vi.restoreAllMocks());

  it("shares one download across concurrent and later consumers", async () => {
    const payload = {metadata: {sceneId: "shared-cache-scene"}};
    const encoded = new TextEncoder().encode(JSON.stringify(payload));
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(
      new ReadableStream({
        start(controller) {
          const midpoint = Math.floor(encoded.length / 2);
          controller.enqueue(encoded.slice(0, midpoint));
          controller.enqueue(encoded.slice(midpoint));
          controller.close();
        },
      }),
      {headers: {"content-length": String(encoded.length)}},
    ));
    const progress = vi.fn();

    const [first, second] = await Promise.all([
      loadStaticScene("shared-cache-scene", new AbortController().signal, progress),
      loadStaticScene("shared-cache-scene", new AbortController().signal, progress),
    ]);
    const third = await loadStaticScene("shared-cache-scene", new AbortController().signal, progress);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(first).toBe(second);
    expect(second).toBe(third);
    expect(progress).toHaveBeenCalledWith(expect.objectContaining({stage: "ready"}));
  });
});
