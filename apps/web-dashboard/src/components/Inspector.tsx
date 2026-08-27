import type {IntersectionNode, IntersectionRealtime} from "../types";

const dash = "—";

export function Inspector({
  node,
  realtime,
}: {
  node: IntersectionNode | null;
  realtime: IntersectionRealtime | null;
}) {
  const lanes = [...(realtime?.lane_states ?? [])]
    .sort((left, right) => right.queue_vehicle_count - left.queue_vehicle_count)
    .slice(0, 8);

  return (
    <aside className="inspector" aria-labelledby="inspector-title">
      <div className="section-heading compact">
        <div>
          <h2 id="inspector-title">路口检查器</h2>
        </div>
      </div>
      {node ? (
        <>
          <div className="intersection-identity">
            <span>
              {node.role === "core_corridor" ? "核心走廊" : "区域控制"}
            </span>
            <strong>{node.display_id}</strong>
            <small>{node.source_label}</small>
            <p>
              {node.lon.toFixed(6)}, {node.lat.toFixed(6)}
            </p>
          </div>
          <dl className="inspector-metrics">
            <div>
              <dt>当前相位 / 灯态</dt>
              <dd>
                {realtime
                  ? `${realtime.phase_id} · ${realtime.phase_state}`
                  : dash}
              </dd>
            </div>
            <div>
              <dt>排队车辆</dt>
              <dd>{realtime?.queue_vehicles ?? dash}</dd>
            </div>
            <div>
              <dt>骑行 / 骑行排队</dt>
              <dd>
                {realtime
                  ? `${realtime.bicycle_count} / ${realtime.bicycle_queue_count}`
                  : dash}
              </dd>
            </div>
            <div>
              <dt>行人 / 等待 / 过街</dt>
              <dd>
                {realtime
                  ? `${realtime.pedestrian_count} / ${realtime.pedestrian_waiting_count} / ${realtime.pedestrian_crossing_count}`
                  : dash}
              </dd>
            </div>
            <div>
              <dt>平均速度</dt>
              <dd>
                {realtime
                  ? `${realtime.mean_speed_m_s.toFixed(1)} m/s`
                  : dash}
              </dd>
            </div>
            <div>
              <dt>拥堵 / 溢出风险</dt>
              <dd>
                {realtime
                  ? `${(realtime.congestion_level * 100).toFixed(0)}% / ${(
                      realtime.spillback_risk * 100
                    ).toFixed(0)}%`
                  : dash}
              </dd>
            </div>
            <div>
              <dt>控制模式</dt>
              <dd className="mode-value">
                {realtime?.control_mode ?? "尚未运行"}
              </dd>
            </div>
          </dl>
          <div className="lane-section">
            <div className="lane-heading">
              <span>车道状态</span>
              <small>按排队量排序</small>
            </div>
            {lanes.length ? (
              <div className="lane-list">
                {lanes.map((lane) => (
                  <div className="lane-row" key={lane.lane_id}>
                    <div>
                      <strong title={lane.lane_id}>{lane.lane_id}</strong>
                      <small>
                        {lane.direction} · {lane.movement}
                      </small>
                    </div>
                    <span>
                      <b>{lane.queue_vehicle_count}</b> veh
                      <small>{lane.queue_length_m.toFixed(0)} m</small>
                    </span>
                    <span>
                      <b>{lane.bicycle_count}</b> bike
                      <small>{lane.pedestrian_waiting_count} ped 等待</small>
                    </span>
                    <span>
                      <b>{(lane.occupancy * 100).toFixed(0)}%</b>
                      <small>
                        下游 {(lane.downstream_occupancy * 100).toFixed(0)}%
                      </small>
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="lane-empty">运行后显示真实 TraCI 车道汇总</p>
            )}
          </div>
          <p className="provenance-note">
            参数来源：
            {node.parameter_provenance === "modeled_from_organizer_data"
              ? "基于主办方数据的数学迁移估计"
              : "主办方路口数据与图像配准位置"}
          </p>
        </>
      ) : (
        <p className="inspector-empty">
          点击拓扑中的路口查看真实运行状态。
        </p>
      )}
    </aside>
  );
}
