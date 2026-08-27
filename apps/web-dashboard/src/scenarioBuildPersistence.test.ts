import {describe, expect, it} from "vitest";
import type {ScenarioBuildRecord} from "./api";
import {selectRestorableScenarioBuild} from "./scenarioBuildPersistence";

function build(id: string, status: ScenarioBuildRecord["status"], hasResult = true): ScenarioBuildRecord {
  return {
    id,
    status,
    progress: status === "completed" ? 100 : 50,
    message: status,
    request: {} as ScenarioBuildRecord["request"],
    validation: {} as ScenarioBuildRecord["validation"],
    logs: [],
    created_at: "2026-08-26T12:00:00+08:00",
    ...(hasResult ? {result: {scenario_id: `scenario-${id}`} as ScenarioBuildRecord["result"]} : {}),
  };
}

describe("scenario build restoration", () => {
  it("restores the preferred successful build from the current browser session", () => {
    const latest = build("latest", "completed");
    const preferred = build("preferred", "completed");

    expect(selectRestorableScenarioBuild([latest, preferred], "preferred")).toBe(preferred);
  });

  it("falls back to the latest successful backend build", () => {
    const running = build("running", "running", false);
    const failed = build("failed", "failed", false);
    const latestCompleted = build("completed", "completed");

    expect(selectRestorableScenarioBuild([running, failed, latestCompleted], "missing")).toBe(latestCompleted);
  });

  it("does not restore a build without a completed result", () => {
    expect(selectRestorableScenarioBuild([build("running", "running", false)], null)).toBeNull();
  });
});
