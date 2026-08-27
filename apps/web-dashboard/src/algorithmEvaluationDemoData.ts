import type {
  BenchmarkAggregateStat,
  BenchmarkPairwiseMetric,
  BenchmarkRanking,
  BenchmarkRecord,
  BenchmarkRow,
  ExperimentEvidence,
  ExperimentEvidencePoint,
} from "./api";

const algorithms = [
  "fixed-time",
  "actuated-control",
  "max-pressure",
  "coordinated-max-pressure",
] as const;
const seeds = [11, 23, 37, 41, 59] as const;
// Positive values represent a harder demand realization for the paired seed.
const seedDemand = [-0.026, 0.018, -0.011, 0.041, -0.034] as const;
const intersectionIds = [
  "容和路—乐民街",
  "容和路—津海大街",
  "悦容路—金湖街",
  "悦容路—双文街",
  "甘棠路—乐安街",
  "甘棠路—明朗街",
  "白塔路—和谐街",
  "白塔路—兴贤街",
] as const;

type DemoAlgorithm = (typeof algorithms)[number];

type DemoProfile = {
  meanSpeed: number;
  meanQueue: number;
  meanWaiting: number;
  completedVehicles: number;
  fuelPerVehicle: number;
  co2PerVehicle: number;
  noxPerVehicle: number;
  emergencyBraking: number;
  conflicts: number;
  accelerationVariance: number;
  latency: number;
  decisionPeak: number;
  ttc: number;
  pet: number;
  queueFactor: number;
};

const profiles: Record<DemoAlgorithm, DemoProfile> = {
  "fixed-time": {
    meanSpeed: 3.56,
    meanQueue: 379,
    meanWaiting: 72.4,
    completedVehicles: 592,
    fuelPerVehicle: 1_390_000,
    co2PerVehicle: 4_285_000,
    noxPerVehicle: 2_030,
    emergencyBraking: 46,
    conflicts: 28_600,
    accelerationVariance: 0.80,
    latency: 16.2,
    decisionPeak: 3.1,
    ttc: 1.05,
    pet: 0.78,
    queueFactor: 1,
  },
  "actuated-control": {
    meanSpeed: 3.66,
    meanQueue: 365,
    meanWaiting: 68.9,
    completedVehicles: 604,
    fuelPerVehicle: 1_352_000,
    co2PerVehicle: 4_165_000,
    noxPerVehicle: 2_015,
    emergencyBraking: 43,
    conflicts: 27_700,
    accelerationVariance: 0.78,
    latency: 18.4,
    decisionPeak: 4.8,
    ttc: 1.09,
    pet: 0.82,
    queueFactor: 0.96,
  },
  "max-pressure": {
    meanSpeed: 3.78,
    meanQueue: 348,
    meanWaiting: 64.6,
    completedVehicles: 619,
    fuelPerVehicle: 1_318_000,
    co2PerVehicle: 4_068_000,
    noxPerVehicle: 1_940,
    emergencyBraking: 40,
    conflicts: 26_400,
    accelerationVariance: 0.76,
    latency: 20.2,
    decisionPeak: 6.9,
    ttc: 1.16,
    pet: 0.88,
    queueFactor: 0.91,
  },
  "coordinated-max-pressure": {
    meanSpeed: 4.05,
    meanQueue: 312,
    meanWaiting: 56.8,
    completedVehicles: 650,
    fuelPerVehicle: 1_244_000,
    co2PerVehicle: 3_846_000,
    noxPerVehicle: 1_965,
    emergencyBraking: 36,
    conflicts: 24_500,
    accelerationVariance: 0.70,
    latency: 24.6,
    decisionPeak: 11.4,
    ttc: 1.30,
    pet: 0.96,
    queueFactor: 0.82,
  },
};

const comparisonMetrics: Array<{key: string; higherBetter: boolean}> = [
  {key: "mean_speed", higherBetter: true},
  {key: "mean_queue_vehicles", higherBetter: false},
  {key: "mean_waiting_time", higherBetter: false},
  {key: "completed_vehicles", higherBetter: true},
  {key: "fuel_per_completed_vehicle_mg", higherBetter: false},
  {key: "co2_per_completed_vehicle_mg", higherBetter: false},
  {key: "nox_per_completed_vehicle_mg", higherBetter: false},
];

function rounded(value: number, digits = 3): number {
  const scale = 10 ** digits;
  return Math.round(value * scale) / scale;
}

function seededUnit(seed: number, label: string): number {
  let hash = (2166136261 ^ seed) >>> 0;
  for (let index = 0; index < label.length; index += 1) {
    hash ^= label.charCodeAt(index);
    hash = Math.imul(hash, 16777619) >>> 0;
  }
  hash ^= hash << 13;
  hash ^= hash >>> 17;
  hash ^= hash << 5;
  return (hash >>> 0) / 4_294_967_295;
}

function metricJitter(seed: number, algorithm: DemoAlgorithm, metric: string, amplitude: number): number {
  return (seededUnit(seed, `${algorithm}:${metric}`) * 2 - 1) * amplitude;
}

function metricStat(values: number[]): BenchmarkAggregateStat {
  const mean = values.reduce((sum, value) => sum + value, 0) / values.length;
  const variance = values.length > 1
    ? values.reduce((sum, value) => sum + (value - mean) ** 2, 0) / (values.length - 1)
    : 0;
  const standardDeviation = Math.sqrt(variance);
  const halfWidth = values.length > 1 ? 2.776 * standardDeviation / Math.sqrt(values.length) : 0;
  return {
    n: values.length,
    mean: rounded(mean),
    standard_deviation: rounded(standardDeviation),
    ci95_low: rounded(mean - halfWidth),
    ci95_high: rounded(mean + halfWidth),
  };
}

function createRow(algorithm: DemoAlgorithm, seed: number, seedIndex: number): BenchmarkRow {
  const profile = profiles[algorithm];
  const demand = seedDemand[seedIndex];
  const speedFactor = 1 - demand * 0.32 + metricJitter(seed, algorithm, "speed", 0.013);
  const queueFactor = 1 + demand * 0.85 + metricJitter(seed, algorithm, "queue", 0.018);
  const waitingFactor = 1 + demand * 0.72 + metricJitter(seed, algorithm, "waiting", 0.021);
  const completionFactor = 1 - demand * 0.38 + metricJitter(seed, algorithm, "completion", 0.009);
  const fuelFactor = 1 + demand * 0.22 + metricJitter(seed, algorithm, "fuel", 0.008);
  const co2Factor = fuelFactor + metricJitter(seed, algorithm, "co2", 0.004);
  const noxFactor = 1 + demand * 0.18 + metricJitter(seed, algorithm, "nox", 0.006);
  const completedVehicles = Math.round(profile.completedVehicles * completionFactor);
  const bicycleShare = 0.295 + metricJitter(seed, algorithm, "bicycle-share", 0.012);
  const bicycleCompleted = Math.round(completedVehicles * bicycleShare);
  const motorCompleted = completedVehicles - bicycleCompleted;
  const conflicts = Math.max(1, Math.round(profile.conflicts * (1 + demand * 0.45 + metricJitter(seed, algorithm, "conflicts", 0.025))));
  const emergencyBraking = Math.max(1, Math.round(profile.emergencyBraking * (1 + demand * 0.55 + metricJitter(seed, algorithm, "braking", 0.045))));
  const fuelPerVehicle = profile.fuelPerVehicle * fuelFactor;
  const co2PerVehicle = profile.co2PerVehicle * co2Factor;
  const actionProfile = algorithm === "fixed-time"
    ? {executed: 36_000, modified: 0, rejected: 0}
    : algorithm === "actuated-control"
      ? {executed: 34_760, modified: 860, rejected: 74}
      : algorithm === "max-pressure"
        ? {executed: 33_940, modified: 1_470, rejected: 118}
        : {executed: 33_180, modified: 2_210, rejected: 164};
  return {
    experiment_id: `preview-rd20-${algorithm}-${seed}-1800`,
    scenario_id: "xiongan_rongdong_20",
    algorithm,
    seed,
    duration_s: 1800,
    evaluation_start_s: 600,
    mean_speed: rounded(profile.meanSpeed * speedFactor),
    mean_speed_m_s: rounded(profile.meanSpeed * speedFactor),
    mean_queue_vehicles: rounded(profile.meanQueue * queueFactor),
    max_queue: rounded(profile.meanQueue * queueFactor * (1.55 + metricJitter(seed, algorithm, "max-queue", 0.06))),
    mean_waiting_time: rounded(profile.meanWaiting * waitingFactor),
    completed_trips: motorCompleted,
    bicycle_completed_trips: bicycleCompleted,
    completed_vehicles: completedVehicles,
    fuel_consumption_mg: rounded(fuelPerVehicle * completedVehicles),
    fuel_per_completed_vehicle_mg: rounded(fuelPerVehicle),
    co2_mg: rounded(co2PerVehicle * completedVehicles),
    co2_per_completed_vehicle_mg: rounded(co2PerVehicle),
    nox_per_completed_vehicle_mg: rounded(profile.noxPerVehicle * noxFactor),
    emergency_braking_count: emergencyBraking,
    emergency_braking_per_1000_completed_vehicles: rounded(emergencyBraking / completedVehicles * 1000),
    motor_motor_conflict_count: Math.ceil(conflicts * 0.5),
    motor_bicycle_conflict_count: Math.ceil(conflicts * 0.22),
    motor_pedestrian_conflict_count: Math.ceil(conflicts * 0.17),
    bicycle_pedestrian_conflict_count: Math.floor(conflicts * 0.11),
    conflicts_per_1000_completed_vehicles: rounded(conflicts / completedVehicles * 1000),
    acceleration_variance: rounded(profile.accelerationVariance * (1 + demand * 0.22 + metricJitter(seed, algorithm, "acceleration", 0.018))),
    end_to_end_control_latency_ms: rounded(profile.latency * (1 + metricJitter(seed, algorithm, "latency", 0.035))),
    algorithm_decision_elapsed_ms_max: rounded(profile.decisionPeak * (1 + metricJitter(seed, algorithm, "decision", 0.06))),
    signal_action_executed_count: Math.round(actionProfile.executed * (1 + metricJitter(seed, algorithm, "executed", 0.007))),
    signal_action_modified_count: Math.round(actionProfile.modified * (1 + metricJitter(seed, algorithm, "modified", 0.035))),
    signal_action_rejected_count: Math.round(actionProfile.rejected * (1 + metricJitter(seed, algorithm, "rejected", 0.05))),
    algorithm_timeout_count: 0,
    algorithm_failure_count: 0,
    fallback_duration_s: 0,
  };
}

const rows = algorithms.flatMap((algorithm) => seeds.map((seed, index) => createRow(algorithm, seed, index)));

function rowValues(algorithm: DemoAlgorithm, key: string): number[] {
  return rows
    .filter((row) => row.algorithm === algorithm)
    .map((row) => row[key])
    .filter((value): value is number => typeof value === "number" && Number.isFinite(value));
}

const aggregate = Object.fromEntries(algorithms.map((algorithm) => [
  algorithm,
  Object.fromEntries(
    [...new Set(rows.filter((row) => row.algorithm === algorithm).flatMap((row) => Object.keys(row)))]
      .map((key) => [key, rowValues(algorithm, key)] as const)
      .filter(([, values]) => values.length)
      .map(([key, values]) => [key, metricStat(values)]),
  ),
])) as Record<string, Record<string, BenchmarkAggregateStat>>;

function createPairwise(): Record<string, Record<string, BenchmarkPairwiseMetric>> {
  return Object.fromEntries(algorithms.slice(0, 3).map((baseline) => [
    baseline,
    Object.fromEntries(comparisonMetrics.map(({key, higherBetter}) => {
      const baselineValues = rowValues(baseline, key);
      const candidateValues = rowValues("coordinated-max-pressure", key);
      const improvements = baselineValues.map((value, index) => higherBetter
        ? (candidateValues[index] - value) / value * 100
        : (value - candidateValues[index]) / value * 100);
      const improvement = metricStat(improvements);
      const winCount = improvements.filter((value) => value > 0).length;
      return [key, {
        n: improvements.length,
        baseline_mean: aggregate[baseline][key].mean,
        b3_mean: aggregate["coordinated-max-pressure"][key].mean,
        improvement_percent: improvement.mean,
        ci95_low: improvement.ci95_low,
        ci95_high: improvement.ci95_high,
        win_count: winCount,
        win_rate: winCount / improvements.length,
        status: improvement.ci95_low > 0
          ? "significant_improvement" as const
          : improvement.mean > 0
            ? "observed_improvement" as const
            : "not_improved" as const,
      }];
    })),
  ]));
}

function createRankings(): Record<string, BenchmarkRanking[]> {
  return Object.fromEntries(comparisonMetrics.map(({key, higherBetter}) => {
    const ordered = algorithms
      .map((algorithm) => ({algorithm, mean: aggregate[algorithm][key].mean}))
      .sort((left, right) => higherBetter ? right.mean - left.mean : left.mean - right.mean);
    return [key, ordered.map((item, index) => ({rank: index + 1, ...item}))];
  }));
}

function gaussian(value: number, center: number, width: number): number {
  return Math.exp(-(((value - center) / width) ** 2));
}

function createEvidence(algorithm: DemoAlgorithm, seed: number, seedIndex: number): ExperimentEvidence {
  const profile = profiles[algorithm];
  const row = rows.find((item) => item.algorithm === algorithm && item.seed === seed)!;
  const times = Array.from({length: 181}, (_, index) => index * 10);
  const demand = seedDemand[seedIndex];
  const response = {
    "fixed-time": {shift: 30, width: 1.10, cycle: 18},
    "actuated-control": {shift: 15, width: 1, cycle: 12},
    "max-pressure": {shift: 0, width: 0.90, cycle: 8},
    "coordinated-max-pressure": {shift: -15, width: 0.78, cycle: 6},
  }[algorithm];
  const rateWeights = times.map((time, index) => {
    const eventLoad = 0.19 * gaussian(time, 500, 150) + 0.12 * gaussian(time, 720, 120) + 0.16 * gaussian(time, 1040, 210);
    const adaptiveGain = algorithm === "coordinated-max-pressure"
      ? 0.075 * gaussian(time, 900, 470)
      : algorithm === "max-pressure"
        ? 0.035 * gaussian(time, 900, 420)
        : algorithm === "actuated-control"
          ? 0.015 * gaussian(time, 760, 360)
          : 0;
    const flowNoise = metricJitter(seed + index * 17, algorithm, "flow-series", 0.055);
    return Math.max(0.35, 1 - eventLoad + adaptiveGain + flowNoise);
  });
  const totalWeight = rateWeights.slice(1).reduce((sum, value) => sum + value, 0);
  let cumulativeWeight = 0;
  let queueNoise = metricJitter(seed, algorithm, "queue-initial", 8);
  const finalCompleted = Number(row.completed_vehicles);
  const finalBicycleShare = Number(row.bicycle_completed_trips) / finalCompleted;
  const probeDistances = [0, 0, 0, 0];
  const intersectionShares = [0.13, 0.16, 0.10, 0.14, 0.11, 0.12, 0.09, 0.15];

  const series: ExperimentEvidencePoint[] = times.map((time, index) => {
    if (index > 0) cumulativeWeight += rateWeights[index];
    queueNoise = queueNoise * 0.76 + metricJitter(seed + index * 31, algorithm, "queue-series", 10);
    const cyclicQueue = response.cycle * Math.sin(time / (algorithm === "fixed-time" ? 21 : 29) + seedIndex * 0.7);
    const baseQueue = 340
      + 18 * Math.sin(Math.PI * time / 1800) ** 2
      + 90 * gaussian(time, 500 + response.shift, 145 * response.width)
      + 60 * gaussian(time, 720 + response.shift, 115 * response.width)
      + 75 * gaussian(time, 1040 + response.shift, 205 * response.width)
      + cyclicQueue;
    const queue = Math.max(175, baseQueue * profile.queueFactor * (1 + demand * 0.72) + queueNoise);
    const completedVehicles = Math.round(finalCompleted * cumulativeWeight / totalWeight);
    const bicycleCompleted = Math.round(completedVehicles * finalBicycleShare);
    const intersectionQueue = Object.fromEntries(intersectionIds.map((id, intersectionIndex) => [
      id,
      rounded(queue * intersectionShares[intersectionIndex] * (0.88 + 0.12 * Math.sin(time / 170 + intersectionIndex * 0.9)), 2),
    ]));
    const eventSlowdown = 0.08 * gaussian(time, 500 + response.shift, 155 * response.width)
      + 0.055 * gaussian(time, 720 + response.shift, 125 * response.width)
      + 0.075 * gaussian(time, 1040 + response.shift, 215 * response.width);
    const speed = Math.max(1.4, profile.meanSpeed * (1 - eventSlowdown - demand * 0.28)
      + metricJitter(seed + index * 19, algorithm, "speed-series", 0.11));
    if (index > 0) probeDistances.forEach((distance, vehicleIndex) => {
      probeDistances[vehicleIndex] = distance + speed * 10 * (0.78 + vehicleIndex * 0.045);
    });
    const probes = Array.from({length: 4}, (_, vehicleIndex) => {
      const progressDistance = probeDistances[vehicleIndex];
      return {
        vehicle_id: `${algorithm.slice(0, 3)}-${vehicleIndex + 1}`,
        road_id: `rd20-road-${vehicleIndex + 1}`,
        lane_id: `rd20-lane-${vehicleIndex + 1}`,
        lane_position_m: rounded(progressDistance % 420, 2),
        x_m: rounded(progressDistance * 0.79 + 12 * Math.sin(progressDistance / 260), 2),
        y_m: rounded(progressDistance * 0.31 + 15 * Math.cos(progressDistance / 310) + vehicleIndex * 18, 2),
        speed_m_s: rounded(speed * (0.94 + vehicleIndex * 0.02), 2),
        waiting_time_s: rounded(profile.meanWaiting * (0.82 + intersectionShares[vehicleIndex] * 0.7), 2),
      };
    });
    const waiting = Math.max(0, profile.meanWaiting * (0.72 + queue / profile.meanQueue * 0.28)
      + metricJitter(seed + index * 23, algorithm, "waiting-series", 2.8));
    const incidentRisk = gaussian(time, 545, 95);
    const safetyNoise = metricJitter(seed + index * 13, algorithm, "safety-series", 0.12);
    const minimumTtc = Math.max(0.05, profile.ttc + 0.13 * Math.sin(time / 137 + seedIndex) - incidentRisk * 0.24 + safetyNoise);
    const minimumPet = Math.max(0.03, profile.pet + 0.10 * Math.cos(time / 163 + seedIndex) - incidentRisk * 0.16 + safetyNoise * 0.7);
    const executedTarget = Number(row.signal_action_executed_count);
    const modifiedTarget = Number(row.signal_action_modified_count);
    const rejectedTarget = Number(row.signal_action_rejected_count);
    return {
      simulation_time_s: 600 + time,
      total_queue_vehicles: rounded(queue * 1.04, 2),
      total_queue_m: rounded(queue * (4.35 + metricJitter(seed + index, algorithm, "queue-length", 0.12)), 2),
      controlled_queue_vehicles: rounded(queue, 2),
      core_corridor_queue_vehicles: rounded(queue * (0.48 + 0.03 * Math.sin(time / 210)), 2),
      mean_speed_m_s: rounded(speed, 2),
      completed_trips: completedVehicles - bicycleCompleted,
      bicycle_completed_trips: bicycleCompleted,
      completed_vehicles: completedVehicles,
      waiting_time_s: rounded(waiting, 2),
      stop_count: Math.round(queue * (0.72 + metricJitter(seed + index, algorithm, "stops", 0.05))),
      spillback_intersections: queue > 430 ? Math.min(4, Math.ceil((queue - 430) / 42)) : 0,
      congested_intersections: Math.max(0, Math.min(8, Math.floor((queue - 245) / 34))),
      fuel_mg: rounded(profile.fuelPerVehicle * (0.78 + queue / 1_450), 2),
      co2_mg: rounded(profile.co2PerVehicle * (0.78 + queue / 1_450), 2),
      nox_mg: rounded(profile.noxPerVehicle * (0.78 + queue / 1_450), 2),
      emergency_braking_count: seededUnit(seed + index * 7, `${algorithm}:brake-event`) < (0.012 + incidentRisk * 0.035) ? 1 : 0,
      acceleration_variance: rounded(profile.accelerationVariance * (0.88 + queue / 3_400) + safetyNoise * 0.04, 3),
      motor_motor_conflict_count: seededUnit(seed + index * 11, `${algorithm}:motor-conflict`) < (0.08 + incidentRisk * 0.06) ? 1 : 0,
      motor_bicycle_conflict_count: seededUnit(seed + index * 17, `${algorithm}:bicycle-conflict`) < (0.035 + incidentRisk * 0.035) ? 1 : 0,
      motor_pedestrian_conflict_count: 0,
      bicycle_pedestrian_conflict_count: 0,
      minimum_ttc_s: rounded(minimumTtc, 2),
      minimum_pet_s: rounded(minimumPet, 2),
      intersection_queue_vehicles: intersectionQueue,
      intersection_mean_speed_m_s: Object.fromEntries(intersectionIds.map((id, intersectionIndex) => [
        id,
        rounded(speed * (0.88 + intersectionIndex * 0.018), 2),
      ])),
      max_downstream_occupancy: rounded(Math.min(0.96, 0.31 + queue / 720), 3),
      vehicle_trajectory_probes: probes,
      cpu_percent: rounded(57 + profile.latency * 0.55 + 3.5 * Math.sin(time / 210) + safetyNoise * 5, 2),
      memory_mb: rounded(176 + seedIndex * 3 + queue * 0.04 + 4 * Math.sin(time / 260), 2),
      fallback_mode: algorithm === "coordinated-max-pressure" ? "CLOUD_COORDINATED" : "LOCAL_CONTROL",
      cloud_online: true,
      mqtt_online: true,
      prediction_status: algorithm === "coordinated-max-pressure" ? "ready" : "not_applicable",
      prediction_model_id: algorithm === "coordinated-max-pressure" ? "xiongan-queue-predictor" : null,
      prediction_horizon_s: algorithm === "coordinated-max-pressure" ? 60 : null,
      prediction_confidence: algorithm === "coordinated-max-pressure" ? rounded(0.84 + 0.04 * Math.sin(time / 190) + safetyNoise * 0.03, 3) : null,
      predicted_queue_vehicles: algorithm === "coordinated-max-pressure" ? rounded(queue * (0.96 + safetyNoise * 0.04), 2) : null,
      predicted_spillback_risk: algorithm === "coordinated-max-pressure" ? rounded(Math.max(0, queue - 350) / 180, 3) : null,
      selected_policy_counts: algorithm === "coordinated-max-pressure" ? {coordinated: index + 1} : null,
      candidate_policy_score_mean: algorithm === "coordinated-max-pressure" ? {coordinated: rounded(0.79 + safetyNoise * 0.08, 3)} : null,
      b3_expected_gain_ratio: algorithm === "coordinated-max-pressure" ? rounded(0.11 + 0.035 * gaussian(time, 900, 430) + safetyNoise * 0.02, 3) : null,
      target_speed_factor_mean: algorithm === "coordinated-max-pressure" ? rounded(0.94 + safetyNoise * 0.025, 3) : null,
      signal_action_executed_count: Math.round(executedTarget * index / (times.length - 1)),
      signal_action_modified_count: Math.round(modifiedTarget * index / (times.length - 1)),
      signal_action_rejected_count: Math.round(rejectedTarget * index / (times.length - 1)),
      signal_action_rejection_reasons: {},
    };
  });

  return {
    experiment_id: String(row.experiment_id),
    scenario_id: String(row.scenario_id),
    algorithm,
    profile: "完整复合场景",
    seed,
    actual_run: false,
    metrics: row,
    source_sample_count: 1801,
    sample_stride: 10,
    series,
  };
}

export const algorithmEvaluationDemoEvidence: ExperimentEvidence[] = algorithms.flatMap((algorithm) =>
  seeds.map((seed, index) => createEvidence(algorithm, seed, index)),
);

const fairnessControls = {
  same_warmup_state: true,
  same_network: true,
  same_od_and_departures_within_seed: true,
  same_vehicle_types: true,
  same_duration: true,
  same_disturbances: true,
  only_algorithm_changes: true,
};

export const algorithmEvaluationDemoBenchmark: BenchmarkRecord = {
  id: "algorithm-evaluation-demo",
  status: "completed",
  progress: 100,
  message: "预置数据已就绪",
  request: {algorithms: [...algorithms], seeds: [...seeds], duration_s: 1800, warmup_s: 600},
  completed_runs: 20,
  total_runs: 20,
  rows,
  result: {
    actual_run: false,
    fairness_controls: fairnessControls,
    algorithms: [...algorithms],
    seeds: [...seeds],
    duration_s: 1800,
    warmup_s: 600,
    rows,
    aggregate_95ci: aggregate,
    input_fingerprints: Object.fromEntries(seeds.map((seed) => [String(seed), ["demo-frozen-input"]])),
    rankings: createRankings(),
    b3_pairwise: createPairwise(),
    b3_verdict: {
      status: "best",
      label: "雄安车路云协同智控在预置矩阵中综合最优",
      seed_count: 5,
      checks: algorithms.slice(0, 3).flatMap((baseline) => [
        {baseline, metric: "mean_queue_vehicles", passed: true},
        {baseline, metric: "mean_speed", passed: true},
      ]),
    },
  },
  error: null,
  created_at: "2026-08-27T00:00:00+08:00",
};
