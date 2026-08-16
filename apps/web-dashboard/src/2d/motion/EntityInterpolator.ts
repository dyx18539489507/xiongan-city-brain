import type {PedestrianEntity, VehicleEntity} from "../../3d/network/digitalTwinTypes";
import type {Point2} from "../../3d/scene/types";

export type MovingEntity = VehicleEntity | PedestrianEntity;
export type RenderEntity<T extends MovingEntity> = T & {renderX: number; renderY: number; renderAngle: number};
type Motion<T extends MovingEntity> = {
  render: RenderEntity<T>;
  fromX: number;
  fromY: number;
  toX: number;
  toY: number;
  fromAngle: number;
  toAngle: number;
  startedAt: number;
  durationMs: number;
};

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}

function shortestAngle(from: number, to: number): number {
  return ((((to - from) % 360) + 540) % 360) - 180;
}

export class EntityInterpolator<T extends MovingEntity> {
  private motions = new Map<string, Motion<T>>();
  private samples: RenderEntity<T>[] = [];
  private trails = new Map<string, Point2[]>();
  private lastUpdateAt: number | null = null;
  private cadenceMs: number | null = null;

  update(entities: ReadonlyMap<string, T>, now: number, tickHz: number): void {
    const durationMs = this.resolveDuration(now, tickHz);
    let membershipChanged = false;
    for (const id of this.motions.keys()) {
      if (!entities.has(id)) {
        this.motions.delete(id);
        this.trails.delete(id);
        membershipChanged = true;
      }
    }
    for (const entity of entities.values()) {
      const current = this.motions.get(entity.id);
      if (current) this.sampleMotion(current, now);
      const fromX = current?.render.renderX ?? entity.x;
      const fromY = current?.render.renderY ?? entity.y;
      const distance = Math.hypot(entity.x - fromX, entity.y - fromY);
      const discontinuity = current !== undefined && distance > 80;
      if (current) {
        const sampledAngle = current.render.renderAngle;
        Object.assign(current.render, entity);
        current.fromX = discontinuity ? entity.x : fromX;
        current.fromY = discontinuity ? entity.y : fromY;
        current.toX = entity.x;
        current.toY = entity.y;
        current.fromAngle = discontinuity ? entity.angle : sampledAngle;
        current.toAngle = entity.angle;
        current.startedAt = now;
        current.durationMs = durationMs;
        if (discontinuity) this.sampleMotion(current, now);
      } else {
        const render = {...entity, renderX: entity.x, renderY: entity.y, renderAngle: entity.angle};
        this.motions.set(entity.id, {
          render,
          fromX: entity.x,
          fromY: entity.y,
          toX: entity.x,
          toY: entity.y,
          fromAngle: entity.angle,
          toAngle: entity.angle,
          startedAt: now,
          durationMs,
        });
        membershipChanged = true;
      }
      const trail = this.trails.get(entity.id) ?? [];
      const last = trail.at(-1);
      if (!last || Math.hypot(last.x - entity.x, last.y - entity.y) > 1.4) {
        trail.push({x: entity.x, y: entity.y});
        if (trail.length > 24) trail.shift();
      }
      this.trails.set(entity.id, trail);
    }
    if (membershipChanged) {
      this.samples.length = 0;
      for (const motion of this.motions.values()) this.samples.push(motion.render);
    }
  }

  sample(now: number): readonly RenderEntity<T>[] {
    for (const motion of this.motions.values()) this.sampleMotion(motion, now);
    return this.samples;
  }

  getTrail(id: string): readonly Point2[] { return this.trails.get(id) ?? []; }

  reset(): void {
    this.motions.clear();
    this.samples.length = 0;
    this.trails.clear();
    this.lastUpdateAt = null;
    this.cadenceMs = null;
  }

  private sampleMotion(motion: Motion<T>, now: number): void {
    const ratio = clamp((now - motion.startedAt) / Math.max(1, motion.durationMs), 0, 1);
    motion.render.renderX = motion.fromX + (motion.toX - motion.fromX) * ratio;
    motion.render.renderY = motion.fromY + (motion.toY - motion.fromY) * ratio;
    motion.render.renderAngle = motion.fromAngle + shortestAngle(motion.fromAngle, motion.toAngle) * ratio;
  }

  private resolveDuration(now: number, tickHz: number): number {
    const nominalMs = clamp(1000 / Math.max(.25, tickHz), 32, 2000);
    if (this.lastUpdateAt !== null) {
      const rawObservedMs = now - this.lastUpdateAt;
      if (Number.isFinite(rawObservedMs) && rawObservedMs > 0 && rawObservedMs <= 5000) {
        // At MAX throughput several SUMO frames may arrive inside one browser
        // frame. Coalesce them into the minimum visible transition window.
        const observedMs = clamp(rawObservedMs, 32, 2000);
        if (
          this.cadenceMs === null
          || observedMs < this.cadenceMs * .55
          || observedMs > this.cadenceMs * 1.8
        ) {
          // Follow intentional simulation-rate changes immediately.
          this.cadenceMs = observedMs;
        } else {
          // Smooth ordinary WebSocket jitter without masking a rate change.
          this.cadenceMs = this.cadenceMs * .7 + observedMs * .3;
        }
      }
    }
    this.lastUpdateAt = now;
    if (this.cadenceMs === null) this.cadenceMs = nominalMs;
    return clamp(this.cadenceMs, 32, 2000);
  }
}
