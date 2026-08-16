import type {Algorithm, IntersectionNode, Scenario, TopologyEdge} from "./types";

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
}) {
  const created = await jsonRequest<{id: string}>("/api/v1/experiments", {
    method: "POST",
    body: JSON.stringify({...input, gui: false}),
  });
  await jsonRequest(`/api/v1/experiments/${created.id}/start`, {method: "POST"});
  return created.id;
}

export async function lifecycle(
  experimentId: string,
  action: "pause" | "resume" | "stop",
) {
  return jsonRequest(`/api/v1/experiments/${experimentId}/${action}`, {method: "POST"});
}

export async function setSimulationRate(experimentId: string, rate: number | null) {
  return jsonRequest(`/api/v1/experiments/${experimentId}/rate`, {
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

export async function clearFaults() {
  return jsonRequest("/api/v1/faults/clear", {method: "POST"});
}
