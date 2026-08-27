export function isActiveRealtimeSnapshot(
  activeExperimentId: string | null,
  incomingExperimentId: string | undefined,
): boolean {
  return Boolean(activeExperimentId) && incomingExperimentId === activeExperimentId;
}
