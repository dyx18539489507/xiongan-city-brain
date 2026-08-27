import type {TimelineEvent} from "../types";

const NOISY_EVENT_PATTERN = /\b(?:EDGE_STATE_PUBLISHED|HEARTBEAT|METRICS?_SNAPSHOT|METRICS?_PUBLISHED|TELEMETRY_SNAPSHOT)\b/i;

export function isOperationalTimelineEvent(event: TimelineEvent): boolean {
  return !NOISY_EVENT_PATTERN.test(`${event.title} ${event.detail}`.replaceAll("-", "_"));
}

export function selectOperationalTimelineEvents(events: readonly TimelineEvent[], limit = 14): TimelineEvent[] {
  if (limit <= 0) return [];
  return events
    .filter(isOperationalTimelineEvent)
    .sort((left, right) => {
      const leftTime = left.simulationTime ?? Number.POSITIVE_INFINITY;
      const rightTime = right.simulationTime ?? Number.POSITIVE_INFINITY;
      return leftTime - rightTime || left.id.localeCompare(right.id);
    })
    .slice(-limit);
}
