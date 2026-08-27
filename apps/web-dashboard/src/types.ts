export type ScenarioProfile = {
  code: string;
  name: string;
  flow_multiplier: number;
  communication_profile: string;
  disturbance_types: string[];
};

export type Scenario = {
  scenario_id: string;
  display_name: string;
  provenance: string;
  is_real_measured_network: boolean;
  duration_s?: number;
  seed?: number;
  runnable: boolean;
  profiles: ScenarioProfile[];
};

export type Algorithm = {
  name: string;
  version: string;
};

export type IntersectionNode = {
  intersection_id: string;
  display_id: string;
  display_name: string;
  source_label: string;
  lon: number;
  lat: number;
  role: "core_corridor" | "controlled";
  parameter_provenance: string;
};

export type TopologyEdge = {
  source: string;
  target: string;
  road_distance_m: number;
};

export type LaneRealtime = {
  lane_id: string;
  direction: string;
  movement: string;
  vehicle_count: number;
  queue_vehicle_count: number;
  bicycle_count: number;
  e_bike_count: number;
  bicycle_queue_count: number;
  pedestrian_count: number;
  pedestrian_waiting_count: number;
  queue_length_m: number;
  mean_speed_m_s: number;
  occupancy: number;
  downstream_occupancy: number;
  downstream_available_capacity: number;
};

export type IntersectionRealtime = {
  intersection_id: string;
  phase_id: string;
  phase_state: string;
  queue_vehicles: number;
  mean_speed_m_s: number;
  congestion_level: number;
  spillback_risk: number;
  control_mode: string;
  incident_state: string;
  bicycle_count: number;
  bicycle_queue_count: number;
  pedestrian_count: number;
  pedestrian_waiting_count: number;
  pedestrian_crossing_count: number;
  emergency_priority_phase_id?: string | null;
  decision_action?: string;
  requested_phase_id?: string | null;
  decision_status?: string;
  decision_reason_codes?: string[];
  decision_explanation?: string;
  phase_scores?: Record<string, number>;
  selected_phase_score?: number | null;
  selected_policy?: string | null;
  expected_gain_ratio?: number | null;
  lane_states: LaneRealtime[];
};

export type RuntimeEvent = {
  simulation_time: number;
  event: string;
  detail?: string;
};

export type RealtimeSnapshot = {
  status: string;
  message?: string;
  experiment_id?: string;
  scenario_id?: string;
  scenario_profile?: string;
  algorithm?: string;
  seed?: number;
  duration_s?: number;
  simulation_time_s?: number;
  simulation_rate?: number | null;
  mean_speed_m_s?: number;
  total_queue_vehicles?: number;
  total_queue_m?: number;
  throughput_vehicles?: number;
  completed_trips?: number;
  bicycle_active_count?: number;
  bicycle_completed_trips?: number;
  bicycle_waiting_time_s?: number;
  bicycle_queue_count?: number;
  pedestrian_active_count?: number;
  pedestrian_completed_trips?: number;
  pedestrian_waiting_time_s?: number;
  pedestrian_crossing_count?: number;
  motor_bicycle_conflict_count?: number;
  motor_pedestrian_conflict_count?: number;
  bicycle_pedestrian_conflict_count?: number;
  minimum_ttc_s?: number | null;
  minimum_pet_s?: number | null;
  waiting_time_s?: number;
  guidance_count?: number;
  guidance_rejection_count?: number;
  max_queue_vehicles?: number;
  downstream_occupancy?: number;
  cpu_percent?: number;
  memory_mb?: number;
  fallback_mode?: string;
  cloud_online?: boolean;
  mqtt_online?: boolean;
  cloud_decision_latency_ms?: number | null;
  edge_decision_latency_ms?: number | null;
  end_to_end_control_latency_ms?: number | null;
  active_disturbances?: string[];
  spillback_edges?: string[];
  congested_intersection_ids?: string[];
  recent_events?: RuntimeEvent[];
  intersections?: IntersectionRealtime[];
};

export type TimelineEvent = {
  id: string;
  simulationTime: number | null;
  type: "state" | "strategy" | "action" | "safety" | "disturbance" | "fault" | "recovery";
  title: string;
  detail: string;
};
