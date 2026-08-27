import {describe, expect, it} from "vitest";
import type {TimelineEvent} from "../types";
import {selectOperationalTimelineEvents} from "./timeline";

function event(id: string, simulationTime: number, detail = id): TimelineEvent {
  return {id, simulationTime, type: "state", title: "运行状态", detail};
}

describe("operational timeline", () => {
  it("filters transport noise and orders meaningful events by simulation time", () => {
    const selected = selectOperationalTimelineEvents([
      event("late", 30, "INCIDENT_STARTED"),
      event("edge", 20, "EDGE_STATE_PUBLISHED"),
      event("early", 10, "CLOUD_OFFLINE"),
      event("heartbeat", 15, "heartbeat"),
      event("metrics", 25, "metrics-snapshot"),
    ]);
    expect(selected.map((item) => item.id)).toEqual(["early", "late"]);
  });

  it("keeps only the most recent fourteen meaningful events", () => {
    const selected = selectOperationalTimelineEvents(
      Array.from({length: 20}, (_, index) => event(`event-${index}`, index)),
    );
    expect(selected).toHaveLength(14);
    expect(selected[0]?.simulationTime).toBe(6);
    expect(selected.at(-1)?.simulationTime).toBe(19);
  });
});
