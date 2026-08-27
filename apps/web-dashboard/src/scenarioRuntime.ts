import type {Scenario} from "./types";

export function resolveScenarioRuntimeParameters(
  scenarios: Scenario[],
  scenarioId: string,
  defaults: {seed: number; durationS: number},
  overrides: {seed?: number; durationS?: number} = {},
): {seed: number; durationS: number} {
  const scenario = scenarios.find((item) => item.scenario_id === scenarioId);
  const isFixedOsmGeneration = scenario?.provenance === "openstreetmap_plus_modeled_parameters"
    && scenario.duration_s === 180;
  if (isFixedOsmGeneration) {
    return {
      seed: scenario.seed ?? defaults.seed,
      durationS: 180,
    };
  }
  return {
    seed: overrides.seed ?? defaults.seed,
    durationS: overrides.durationS ?? defaults.durationS,
  };
}
