import * as THREE from "three";

export type InterpolatedTransform = {
  position: THREE.Vector3;
  quaternion: THREE.Quaternion;
};

export class VehicleInterpolator {
  private readonly previousPosition = new THREE.Vector3();
  private readonly targetPosition = new THREE.Vector3();
  private readonly previousQuaternion = new THREE.Quaternion();
  private readonly targetQuaternion = new THREE.Quaternion();
  private readonly currentPosition = new THREE.Vector3();
  private readonly currentQuaternion = new THREE.Quaternion();
  private startedAtMs = 0;
  private durationMs = 1;
  private initialized = false;

  snap(position: THREE.Vector3, quaternion: THREE.Quaternion, nowMs: number): void {
    this.previousPosition.copy(position);
    this.targetPosition.copy(position);
    this.previousQuaternion.copy(quaternion);
    this.targetQuaternion.copy(quaternion);
    this.startedAtMs = nowMs;
    this.durationMs = 1;
    this.initialized = true;
  }

  retarget(
    position: THREE.Vector3,
    quaternion: THREE.Quaternion,
    nowMs: number,
    durationMs: number,
  ): void {
    if (!this.initialized) {
      this.snap(position, quaternion, nowMs);
      return;
    }
    this.sample(nowMs, {
      position: this.currentPosition,
      quaternion: this.currentQuaternion,
    });
    this.previousPosition.copy(this.currentPosition);
    this.previousQuaternion.copy(this.currentQuaternion);
    this.targetPosition.copy(position);
    this.targetQuaternion.copy(quaternion);
    this.startedAtMs = nowMs;
    this.durationMs = Math.max(1, durationMs);
  }

  sample(nowMs: number, output: InterpolatedTransform): InterpolatedTransform {
    const alpha = THREE.MathUtils.clamp(
      (nowMs - this.startedAtMs) / this.durationMs,
      0,
      1,
    );
    output.position.lerpVectors(this.previousPosition, this.targetPosition, alpha);
    output.quaternion.slerpQuaternions(
      this.previousQuaternion,
      this.targetQuaternion,
      alpha,
    );
    return output;
  }
}
