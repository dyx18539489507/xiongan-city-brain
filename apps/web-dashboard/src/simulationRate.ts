export type SimulationRateSample = {
  simulationTimeS: number;
  wallTimeMs: number;
};

export function calculateEffectiveSimulationRate(
  samples: readonly SimulationRateSample[],
): number | null {
  if (samples.length < 2) return null;
  const first = samples[0];
  const last = samples[samples.length - 1];
  const wallDeltaS = (last.wallTimeMs - first.wallTimeMs) / 1000;
  const simulationDeltaS = last.simulationTimeS - first.simulationTimeS;
  if (wallDeltaS <= 0 || simulationDeltaS < 0) return null;
  return simulationDeltaS / wallDeltaS;
}

export function appendSimulationRateSample(
  samples: readonly SimulationRateSample[],
  sample: SimulationRateSample,
  windowMs = 4_000,
): SimulationRateSample[] {
  const previous = samples.at(-1);
  if (previous && sample.simulationTimeS < previous.simulationTimeS) return [sample];
  if (previous?.simulationTimeS === sample.simulationTimeS) return [...samples];
  const cutoff = sample.wallTimeMs - windowMs;
  const recent = samples.filter((item) => item.wallTimeMs >= cutoff);
  return [...recent, sample].slice(-40);
}
