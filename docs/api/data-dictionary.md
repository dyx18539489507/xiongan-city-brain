# 数据字典

机器可读源为 `specs/data_dictionary.yaml`，严格类型与必填规则以 `specs/jsonschema/` 为准。比例统一为 0–1；速度为 m/s，距离为 m，时间为 s，时延为 ms，流量为 veh/h，加速度为 m/s²。排队同时保留 veh 和 m。

## 公共消息字段

所有正式消息都包含下列公共字段。

| 字段 | 类型/单位 | 含义 |
|---|---|---|
| schema_version | string | 契约版本 |
| message_id | UUID | 幂等键 |
| trace_id | string | 云、边、车、实验全链路追踪 |
| source_id / source_type | string / enum | 发布实例与 cloud/rsu/edge/vehicle/experiment/report/system |
| timestamp_utc | UTC datetime | 观测时间 |
| simulation_time | number, s | SUMO 仿真时间 |
| sequence_number | integer | 同一来源单调序号 |
| created_at / expires_at | UTC datetime | 创建与过期时间；过期消息拒绝 |
| correlation_id | string | 请求、策略和反馈关联键 |
| environment | string | development/test/production |
| scenario_id / experiment_id | string | 场景与实验隔离键 |

## 模型字段与频率

| 模型 | 模型专有字段（字段后为单位） | 典型频率 |
|---|---|---|
| VehicleState | vehicle_id；vehicle_type；connected；road_id；lane_id；position_xy(m)；lane_position(m)；speed(m/s)；acceleration(m/s²)；heading(degree)；route_id；next_intersection_id；distance_to_stop_line(m)；turn_direction；waiting_time(s)；stop_count(count)；emission_estimate(mg/s)；fuel_consumption_estimate(mg/s) | 控制车辆 1 Hz；完整轨迹默认 0.2 Hz |
| BicycleState | bicycle_id；bicycle_type(bicycle/e_bike)；road_id；lane_id；position_xy(m)；lane_position(m)；speed(m/s)；acceleration(m/s²)；route_id；next_intersection_id；distance_to_stop_line(m)；waiting_time(s) | 1 Hz 聚合；完整轨迹默认 0.2 Hz |
| PedestrianState | pedestrian_id；person_type；road_id；lane_id；position_xy(m)；speed(m/s)；waiting_time(s)；crossing_id；stage_index | 1 Hz 聚合；完整轨迹默认 0.2 Hz |
| LaneState | 原有机动车字段；另含 bicycle_count、electric_bicycle_count、bicycle_queue_count、bicycle_queue_length_m、pedestrian_count、pedestrian_waiting_count | 1 Hz |
| IntersectionState | 原有信号和机动车字段；另含 bicycle_count、bicycle_queue_count、pedestrian_count、pedestrian_waiting_count、pedestrian_crossing_count | 1 Hz |
| RegionalState | intersection_states；network_mean_speed(m/s)；total_queue(veh)；congested_intersections；spillback_edges；risk_levels(0–1)；active_disturbances | 1 Hz；云策略默认 0.2 Hz |
| CloudStrategy | strategy_id；strategy_version；generated_at_sim_time(s)；valid_from(s)；valid_until(s)；target_intersection_id；target_cycle_length(s)；target_green_ratios(0–1)；target_offsets(s)；upstream_release_limit(0–1)；downstream_priority(weight)；recommended_phase_plan；speed_guidance_parameters；confidence(0–1)；reason_codes；fallback_policy | 默认每 5 s |
| EdgeControlAction | action_id；intersection_id；requested_phase_id；action_type；requested_duration(s)；source_strategy_id；validation_status；rejection_reasons；applied_at(s)；expected_effect；recommended_speed_m_s(m/s) | 每控制步 |
| ExecutionFeedback | action_id；strategy_id；intersection_id；requested_action；executed_action；execution_status；rejection_reason；control_mode；command_latency_ms(ms)；cloud_round_trip_latency_ms(ms)；actual_start_time(s)；actual_end_time(s)；observed_effect | 每动作 |
| CommunicationEvent | channel；source；destination；message_type；configured_latency_ms(ms)；actual_latency_ms(ms)；dropped；duplicated；reordered；corrupted；timeout；recovery_time(s) | 每消息或异常 |
| FaultEvent | fault_type；target；severity；start_time(s)；duration(s)；injected_by；recovery_policy；recovery_status | 事件触发 |
| SafetyConflictEvent | participant_a/b；participant_a/b_type；conflict_type；location_xy(m)；minimum_distance_m；ttc_s；pet_s；relative_speed_m_s；severity；data_source | 每个观测冲突 |

`action_type` 支持 `hold_phase`、`extend_green`、`terminate_phase`、`request_next_phase`、`change_cycle_target`、`apply_speed_guidance`、`fallback_fixed_time`。模型使用 Pydantic 严格模式、禁止额外字段；19 份 JSON Schema 由 `traffic-platform validate` 重新生成并校验。

轨迹批次使用 `participant_kind=motor_vehicle|bicycle|pedestrian` 区分交通主体。TTC/PET 来自 SUMO 轨迹观测算法，是仿真代理安全指标，不代表现场事故或经实测校准的冲突结论。
