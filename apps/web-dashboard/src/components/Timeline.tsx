import type {TimelineEvent} from "../types";

export function Timeline({events}: {events: TimelineEvent[]}) {
  return (
    <section className="timeline" aria-labelledby="timeline-title">
      <div className="section-heading compact">
        <div>
          <h2 id="timeline-title">事件时间线</h2>
        </div>
        <span className="count-label">{events.length} 条</span>
      </div>
      <ol>
        {events.length ? (
          events.slice(0, 18).map((event) => (
            <li key={event.id} className={`event-${event.type}`}>
              <time>
                {event.simulationTime === null
                  ? "系统"
                  : `T+${event.simulationTime.toFixed(0)}s`}
              </time>
              <div>
                <strong>{event.title}</strong>
                <p>{event.detail}</p>
              </div>
            </li>
          ))
        ) : (
          <li className="timeline-empty">
            实验事件将在这里按真实发生顺序出现
          </li>
        )}
      </ol>
    </section>
  );
}
