import type {Algorithm, IntersectionNode, Scenario, TopologyEdge} from "./types";

export type ScenarioBuildRequest = {
  scenario_id: string;
  display_name: string;
  source_type: "current_osm" | "osm_bbox" | "planning_file";
  draft_id?: string;
  selected_intersection_ids: string[];
  seed: number;
  traffic_demand?: {
    source: "synthetic";
    target_flow_veh_h: number;
    duration_s: number;
    od_pattern: "network_wide" | "boundary_exchange" | "boundary_dominant";
    min_trip_distance_m: number;
  } | null;
};

export type ScenarioDraftRoad = {
  id: string;
  coordinates: number[][];
  lane_count?: number;
  speed_m_s?: number;
};

export type ScenarioDraftIntersection = {
  intersection_id: string;
  display_id: string;
  display_name: string;
  x: number;
  y: number;
  lon?: number | null;
  lat?: number | null;
  degree: number;
  signalized: boolean;
};

export type ScenarioDraft = {
  id: string;
  status: "queued" | "processing" | "ready" | "failed";
  progress: number;
  message: string;
  source_type: "osm_bbox" | "planning_file";
  source: Record<string, unknown>;
  coordinate_mode: "geographic" | "local";
  confidence: "unknown" | "low" | "medium" | "high";
  requires_manual_review: boolean;
  review_confirmed: boolean;
  preview: {
    bounds: {min_x: number; min_y: number; max_x: number; max_y: number} | null;
    roads: ScenarioDraftRoad[];
    buildings: Array<{id: string; coordinates: number[][]}>;
    intersections: ScenarioDraftIntersection[];
    topology_edges: TopologyEdge[];
  };
  selected_intersection_ids: string[];
  manual_edits: Array<{time: string; type: string}>;
  validation: ScenarioBuildValidation | null;
  artifacts: Record<string, string>;
  logs: Array<{time: string; progress: number; message: string}>;
  error?: string | null;
  created_at: string;
  updated_at: string;
};

export type ScenarioBuildValidation = {
  valid: boolean;
  selected_intersection_count: number;
  selected_intersection_ids: string[];
  connected_control_subgraph?: boolean | null;
  errors: string[];
  warnings: string[];
  rule: string;
};

export type ScenarioBuildRecord = {
  id: string;
  status: "queued" | "running" | "completed" | "failed";
  progress: number;
  message: string;
  request: ScenarioBuildRequest;
  validation: ScenarioBuildValidation;
  logs: Array<{time: string; progress: number; message: string}>;
  result?: {
    scenario_id: string;
    version: string;
    selected_intersection_count: number;
    connected_control_subgraph?: boolean | null;
    warnings: string[];
    sumo_config: string;
    traffic_demand?: {
      actual?: {
        routed_vehicle_count?: number;
        achieved_flow_veh_h?: number;
      };
      requested?: ScenarioBuildRequest["traffic_demand"];
    };
  } | null;
  error?: string | null;
  created_at: string;
};

export type BenchmarkRequest = {
  algorithms: string[];
  seeds: number[];
  duration_s: number;
  warmup_s?: number;
};

export type BenchmarkRow = Record<string, number | string | boolean | null> & {
  experiment_id: string;
  scenario_id: string;
  algorithm: string;
  seed: number;
  duration_s: number;
};

export type BenchmarkAggregateStat = {
  n: number;
  mean: number;
  standard_deviation: number;
  ci95_low: number;
  ci95_high: number;
};

export type BenchmarkPairwiseMetric = {
  n: number;
  baseline_mean: number;
  b3_mean: number;
  improvement_percent: number | null;
  ci95_low: number | null;
  ci95_high: number | null;
  win_count: number;
  win_rate: number;
  status: "significant_improvement" | "observed_improvement" | "not_improved";
};

export type BenchmarkRanking = {
  rank: number;
  algorithm: string;
  mean: number;
};

export type BenchmarkVerdict = {
  status: "best" | "not_proven" | "insufficient_evidence";
  label: string;
  seed_count: number;
  checks: Array<{baseline: string; metric: string; passed: boolean}>;
};

export type BenchmarkRecord = {
  id: string;
  status: "queued" | "running" | "completed" | "failed";
  progress: number;
  message: string;
  request: BenchmarkRequest;
  completed_runs: number;
  total_runs: number;
  rows: BenchmarkRow[];
  result?: {
    actual_run: boolean;
    fairness_controls: Record<string, boolean>;
    algorithms: string[];
    seeds: number[];
    duration_s: number;
    warmup_s: number;
    rows: BenchmarkRow[];
    aggregate_95ci: Record<string, Record<string, BenchmarkAggregateStat>>;
    input_fingerprints: Record<string, string[]>;
    rankings: Record<string, BenchmarkRanking[]>;
    b3_pairwise: Record<string, Record<string, BenchmarkPairwiseMetric>>;
    b3_verdict: BenchmarkVerdict;
  } | null;
  error?: string | null;
  created_at: string;
};

export type ExperimentEvidencePoint = {
  simulation_time_s: number;
  total_queue_vehicles?: number | null;
  total_queue_m?: number | null;
  controlled_queue_vehicles: number;
  core_corridor_queue_vehicles: number;
  mean_speed_m_s: number;
  completed_trips?: number | null;
  bicycle_completed_trips?: number | null;
  completed_vehicles?: number | null;
  waiting_time_s?: number | null;
  stop_count?: number | null;
  spillback_intersections?: number | null;
  congested_intersections?: number | null;
  fuel_mg?: number | null;
  co2_mg?: number | null;
  nox_mg?: number | null;
  emergency_braking_count?: number | null;
  acceleration_variance?: number | null;
  motor_motor_conflict_count?: number | null;
  motor_bicycle_conflict_count?: number | null;
  motor_pedestrian_conflict_count?: number | null;
  bicycle_pedestrian_conflict_count?: number | null;
  minimum_ttc_s?: number | null;
  minimum_pet_s?: number | null;
  intersection_queue_vehicles?: Record<string, number> | null;
  intersection_mean_speed_m_s?: Record<string, number> | null;
  max_downstream_occupancy?: number | null;
  vehicle_trajectory_probes?: Array<{
    vehicle_id: string;
    road_id: string;
    lane_id: string;
    lane_position_m: number;
    x_m: number;
    y_m: number;
    speed_m_s: number;
    waiting_time_s: number;
  }> | null;
  cpu_percent?: number | null;
  memory_mb?: number | null;
  fallback_mode?: string | null;
  cloud_online?: boolean | null;
  mqtt_online?: boolean | null;
  prediction_status?: string | null;
  prediction_model_id?: string | null;
  prediction_horizon_s?: number | null;
  prediction_confidence?: number | null;
  predicted_queue_vehicles?: number | null;
  predicted_spillback_risk?: number | null;
  selected_policy_counts?: Record<string, number> | null;
  candidate_policy_score_mean?: Record<string, number> | null;
  b3_expected_gain_ratio?: number | null;
  target_speed_factor_mean?: number | null;
  signal_action_executed_count?: number | null;
  signal_action_modified_count?: number | null;
  signal_action_rejected_count?: number | null;
  signal_action_rejection_reasons?: Record<string, number> | null;
};

export type ExperimentEvidence = {
  experiment_id: string;
  scenario_id: string;
  algorithm: string;
  profile: string;
  seed: number;
  actual_run: boolean;
  metrics: Record<string, number | string | boolean | null>;
  source_sample_count: number;
  sample_stride: number;
  series: ExperimentEvidencePoint[];
};

export type ExperimentState = {
  id: string;
  status: string;
  request: {
    scenario_id: string;
    profile: string;
    algorithm: string;
    seed: number;
    duration_s: number;
  };
  error?: string | null;
};

async function jsonRequest<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    headers: {"content-type": "application/json", ...(init?.headers ?? {})},
    ...init,
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`${response.status} ${body}`);
  }
  return response.json() as Promise<T>;
}

export function describeRequestError(reason: unknown): string {
  const message = reason instanceof Error ? reason.message : String(reason);
  const responseMatch = message.match(/^(?:Error:\s*)?(\d{3})\b\s*([\s\S]*)$/);
  const status = responseMatch ? Number(responseMatch[1]) : null;
  const responseBody = responseMatch?.[2].trim() ?? "";
  let detail = responseBody;
  if (responseBody.startsWith("{")) {
    try {
      const payload = JSON.parse(responseBody) as {message?: unknown; detail?: unknown};
      const candidate = payload.message ?? payload.detail;
      if (typeof candidate === "string") detail = candidate;
    } catch {
      // Preserve a non-standard response body verbatim.
    }
  }
  const conflictMessages: Record<string, string> = {
    "a live comparison is already active": "已有双路实时对照正在运行",
    "stop the live comparison before creating a single experiment": "请先停止双路实时对照，再启动单路仿真",
    "stop the single experiment before creating a live comparison": "请先停止单路仿真，再启动双路实时对照",
    "wait for the algorithm benchmark before creating a live comparison": "算法批量评测仍在运行，请等待评测完成后再启动实时对照",
  };
  if (status === 409) return conflictMessages[detail] ?? `当前操作与运行状态冲突${detail ? `：${detail}` : ""}`;
  if (status !== null && status >= 400 && status < 500 && detail) return detail;
  if (status !== null) return `后端服务暂不可用（HTTP ${status}），请确认 API 服务已启动`;
  if (/fetch|network|connection/i.test(message)) return "暂时无法连接后端服务，请确认 API 服务已启动";
  return message || "操作失败，请稍后重试";
}

export async function loadInventory() {
  const [scenarioPayload, algorithmPayload, intersectionPayload] = await Promise.all([
    jsonRequest<{items: Scenario[]}>("/api/v1/scenarios"),
    jsonRequest<{items: Algorithm[]; active: string}>("/api/v1/algorithms"),
    jsonRequest<{items: IntersectionNode[]; topology_edges: TopologyEdge[]}>("/api/v1/intersections"),
  ]);
  return {
    scenarios: scenarioPayload.items,
    algorithms: algorithmPayload.items,
    intersections: intersectionPayload.items,
    topologyEdges: intersectionPayload.topology_edges,
    activeAlgorithm: algorithmPayload.active,
  };
}

export async function createAndStartExperiment(input: {
  scenario_id: string;
  profile: string;
  algorithm: string;
  seed: number;
  duration_s: number;
}, simulationRate: number | null) {
  const created = await jsonRequest<{id: string}>("/api/v1/experiments", {
    method: "POST",
    body: JSON.stringify({...input, gui: false}),
  });
  await setSimulationRate(created.id, simulationRate);
  await jsonRequest(`/api/v1/experiments/${created.id}/start`, {method: "POST"});
  return created.id;
}

export async function lifecycle(
  experimentId: string,
  action: "pause" | "resume" | "stop",
) {
  return jsonRequest(`/api/v1/experiments/${experimentId}/${action}`, {method: "POST"});
}

export function loadExperimentState(experimentId: string) {
  return jsonRequest<ExperimentState>(
    `/api/v1/experiments/${experimentId}`,
    {cache: "no-store"},
  );
}

export async function setSimulationRate(experimentId: string, rate: number | null) {
  return jsonRequest(`/api/v1/experiments/${experimentId}/rate`, {
    method: "POST",
    body: JSON.stringify({rate}),
  });
}

export async function createAndStartLiveComparison(input: {
  scenario_id: string;
  profile: string;
  baseline_algorithm: string;
  candidate_algorithm: string;
  seed: number;
  duration_s: number;
}, simulationRate: number | null, onStage?: (stage: "creating" | "configuring" | "starting") => void) {
  onStage?.("creating");
  const created = await jsonRequest<{id: string; fairness_fingerprint: string}>(
    "/api/v1/live-comparisons",
    {method: "POST", body: JSON.stringify({...input, gui: false})},
  );
  onStage?.("configuring");
  await setLiveComparisonRate(created.id, simulationRate);
  onStage?.("starting");
  await jsonRequest(`/api/v1/live-comparisons/${created.id}/start`, {method: "POST"});
  return created;
}

export async function liveComparisonLifecycle(
  pairId: string,
  action: "start" | "pause" | "resume" | "stop",
) {
  return jsonRequest(`/api/v1/live-comparisons/${pairId}/${action}`, {method: "POST"});
}

export async function setLiveComparisonRate(pairId: string, rate: number | null) {
  return jsonRequest(`/api/v1/live-comparisons/${pairId}/rate`, {
    method: "POST",
    body: JSON.stringify({rate}),
  });
}

export async function injectFault(
  fault_type: string,
  target: string,
  parameters: Record<string, number | string | boolean> = {},
  durationS = 30,
) {
  return jsonRequest<{id: string}>("/api/v1/faults/inject", {
    method: "POST",
    body: JSON.stringify({
      fault_type,
      target,
      severity: "medium",
      duration_s: durationS,
      parameters,
    }),
  });
}

export async function injectLiveComparisonFault(
  pairId: string,
  fault_type: string,
  target: string,
  parameters: Record<string, number | string | boolean> = {},
  durationS = 30,
) {
  return jsonRequest<{id: string; pair_id: string; experiment_ids: string[]}>(
    `/api/v1/live-comparisons/${pairId}/faults/inject`,
    {
      method: "POST",
      body: JSON.stringify({
        fault_type,
        target,
        severity: "medium",
        duration_s: durationS,
        parameters,
      }),
    },
  );
}

export async function clearLiveComparisonFaults(pairId: string) {
  return jsonRequest<{pair_id: string; cleared: number}>(
    `/api/v1/live-comparisons/${pairId}/faults/clear`,
    {method: "POST"},
  );
}

export async function clearFaults() {
  return jsonRequest("/api/v1/faults/clear", {method: "POST"});
}

export async function validateScenarioBuild(input: ScenarioBuildRequest) {
  return jsonRequest<ScenarioBuildValidation>("/api/v1/scenario-builds/validate", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function createOsmScenarioDraft(bbox: {
  west: number;
  south: number;
  east: number;
  north: number;
}) {
  return jsonRequest<{id: string; status: string}>("/api/v1/scenario-drafts/osm", {
    method: "POST",
    body: JSON.stringify({bbox}),
  });
}

export async function createPlanningScenarioDraft(file: File) {
  const response = await fetch("/api/v1/scenario-drafts/planning", {
    method: "POST",
    headers: {
      "content-type": file.type || "application/octet-stream",
      "x-file-name": encodeURIComponent(file.name),
    },
    body: file,
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${await response.text()}`);
  }
  return response.json() as Promise<{id: string; status: string}>;
}

export async function loadScenarioDraft(draftId: string) {
  return jsonRequest<ScenarioDraft>(`/api/v1/scenario-drafts/${draftId}`, {
    cache: "no-store",
  });
}

export async function loadScenarioDrafts() {
  return jsonRequest<{items: ScenarioDraft[]}>("/api/v1/scenario-drafts", {
    cache: "no-store",
  });
}

export async function patchScenarioDraft(
  draftId: string,
  update: Partial<Pick<ScenarioDraft, "selected_intersection_ids" | "review_confirmed">> & {
    roads?: ScenarioDraftRoad[];
    intersections?: ScenarioDraftIntersection[];
  },
) {
  return jsonRequest<ScenarioDraft>(`/api/v1/scenario-drafts/${draftId}`, {
    method: "PATCH",
    body: JSON.stringify(update),
  });
}

export function scenarioDraftArtifactUrl(draftId: string, artifactKey: string) {
  return `/api/v1/scenario-drafts/${encodeURIComponent(draftId)}/artifacts/${encodeURIComponent(artifactKey)}`;
}

export async function createScenarioBuild(input: ScenarioBuildRequest) {
  return jsonRequest<{id: string; status: string; validation: ScenarioBuildValidation}>(
    "/api/v1/scenario-builds",
    {method: "POST", body: JSON.stringify(input)},
  );
}

export async function loadScenarioBuild(buildId: string) {
  return jsonRequest<ScenarioBuildRecord>(`/api/v1/scenario-builds/${buildId}`, {
    cache: "no-store",
  });
}

export async function loadScenarioBuilds() {
  return jsonRequest<{items: ScenarioBuildRecord[]}>("/api/v1/scenario-builds", {
    cache: "no-store",
  });
}

export async function openScenarioFolder(scenarioId: string) {
  return jsonRequest<{opened: true; scenario_id: string}>(
    `/api/v1/scenarios/${encodeURIComponent(scenarioId)}/open-folder`,
    {method: "POST"},
  );
}

export async function openScenarioInSumo(scenarioId: string) {
  return jsonRequest<{opened: true; scenario_id: string; config_file: string}>(
    `/api/v1/scenarios/${encodeURIComponent(scenarioId)}/open-sumo`,
    {method: "POST"},
  );
}

export async function createBenchmark(input: BenchmarkRequest) {
  return jsonRequest<{id: string; status: string; total_runs: number}>(
    "/api/v1/benchmarks",
    {method: "POST", body: JSON.stringify(input)},
  );
}

export async function loadBenchmark(id: string) {
  return jsonRequest<BenchmarkRecord>(`/api/v1/benchmarks/${id}`, {cache: "no-store"});
}

export async function loadBenchmarks() {
  return jsonRequest<{items: BenchmarkRecord[]}>("/api/v1/benchmarks", {cache: "no-store"});
}

export async function loadExperimentEvidence(id: string) {
  return jsonRequest<ExperimentEvidence>(
    `/api/v1/experiments/${encodeURIComponent(id)}/evidence`,
    {cache: "no-store"},
  );
}
