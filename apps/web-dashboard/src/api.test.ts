import {afterEach, describe, expect, it, vi} from "vitest";
import {createAndStartExperiment, createAndStartLiveComparison, describeRequestError, injectLiveComparisonFault} from "./api";

function jsonResponse(payload: unknown): Response {
  return {
    ok: true,
    json: async () => payload,
    text: async () => JSON.stringify(payload),
  } as Response;
}

afterEach(() => vi.unstubAllGlobals());

describe("experiment startup", () => {
  it("configures pacing before SUMO starts", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({id: "exp-1"}))
      .mockResolvedValueOnce(jsonResponse({id: "exp-1", simulation_rate: 1}))
      .mockResolvedValueOnce(jsonResponse({id: "exp-1", status: "starting"}));
    vi.stubGlobal("fetch", fetchMock);

    await createAndStartExperiment({
      scenario_id: "xiongan_rongdong_20",
      profile: "BASE",
      algorithm: "coordinated-max-pressure",
      seed: 42,
      duration_s: 1800,
    }, 1);

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "/api/v1/experiments",
      "/api/v1/experiments/exp-1/rate",
      "/api/v1/experiments/exp-1/start",
    ]);
  });

  it("reports each paired SUMO startup stage in request order", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({id: "pair-1", fairness_fingerprint: "abc"}))
      .mockResolvedValueOnce(jsonResponse({id: "pair-1", simulation_rate: 1}))
      .mockResolvedValueOnce(jsonResponse({id: "pair-1", status: "starting"}));
    vi.stubGlobal("fetch", fetchMock);
    const stages: string[] = [];

    await createAndStartLiveComparison({
      scenario_id: "xiongan_rongdong_20",
      profile: "BASE",
      baseline_algorithm: "fixed-time",
      candidate_algorithm: "coordinated-max-pressure",
      seed: 42,
      duration_s: 1800,
    }, 1, (stage) => stages.push(stage));

    expect(stages).toEqual(["creating", "configuring", "starting"]);
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "/api/v1/live-comparisons",
      "/api/v1/live-comparisons/pair-1/rate",
      "/api/v1/live-comparisons/pair-1/start",
    ]);
  });

  it("targets a fault at one paired runtime", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse({
      id: "fault-1",
      pair_id: "pair-1",
      experiment_ids: ["pair-1-baseline", "pair-1-candidate"],
    }));
    vi.stubGlobal("fetch", fetchMock);

    await injectLiveComparisonFault("pair-1", "cloud_offline", "cloud", {}, 30);

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/live-comparisons/pair-1/faults/inject",
      expect.objectContaining({method: "POST"}),
    );
  });
});

describe("request error presentation", () => {
  it("turns HTTP failures into one readable service message", () => {
    expect(describeRequestError(new Error("502 Bad Gateway"))).toBe("后端服务暂不可用（HTTP 502），请确认 API 服务已启动");
  });

  it("keeps domain validation details intact", () => {
    expect(describeRequestError(new Error("受控路口必须形成连通子图"))).toBe("受控路口必须形成连通子图");
  });

  it("shows the real reason for an HTTP conflict", () => {
    expect(describeRequestError(new Error(
      '409 {"error_code":"INVALID_STATE_TRANSITION","message":"stop the single experiment before creating a live comparison"}',
    ))).toBe("请先停止单路仿真，再启动双路实时对照");
  });

  it("keeps structured client-error details", () => {
    expect(describeRequestError(new Error(
      '422 {"message":"候选算法与基准算法不能相同"}',
    ))).toBe("候选算法与基准算法不能相同");
  });
});
