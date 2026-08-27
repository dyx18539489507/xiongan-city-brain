import type {ExperimentState} from "./api";

const reusableExperimentStatuses = new Set(["starting", "running", "paused"]);

export function canReuseExperiment(state: ExperimentState, scenarioId: string): boolean {
  return state.request.scenario_id === scenarioId && reusableExperimentStatuses.has(state.status);
}
