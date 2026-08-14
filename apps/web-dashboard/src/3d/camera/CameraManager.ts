import * as THREE from "three";

export type CameraPose = {
  position: readonly [number, number, number];
  target: readonly [number, number, number];
  fov: number;
  transitionDuration: number;
};

type TargetControls = {
  target: THREE.Vector3;
};

export class CameraManager {
  private startPosition = new THREE.Vector3();
  private startTarget = new THREE.Vector3();
  private targetPosition = new THREE.Vector3();
  private targetTarget = new THREE.Vector3();
  private startFov = 43;
  private targetFov = 43;
  private durationMs = 1;
  private elapsedMs = 0;
  private transitioning = false;

  constructor(
    private readonly camera: THREE.PerspectiveCamera,
    private readonly controls: TargetControls,
  ) {}

  transitionTo(pose: CameraPose): void {
    this.startPosition.copy(this.camera.position);
    this.startTarget.copy(this.controls.target);
    this.targetPosition.fromArray(pose.position);
    this.targetTarget.fromArray(pose.target);
    this.startFov = this.camera.fov;
    this.targetFov = pose.fov;
    this.durationMs = Math.max(1, pose.transitionDuration);
    this.elapsedMs = 0;
    this.transitioning = true;
  }

  update(deltaMs: number): boolean {
    if (!this.transitioning) return false;
    this.elapsedMs = Math.min(this.durationMs, this.elapsedMs + Math.max(0, deltaMs));
    const linear = this.elapsedMs / this.durationMs;
    const eased = linear < 0.5
      ? 4 * linear * linear * linear
      : 1 - Math.pow(-2 * linear + 2, 3) / 2;
    this.camera.position.lerpVectors(this.startPosition, this.targetPosition, eased);
    this.controls.target.lerpVectors(this.startTarget, this.targetTarget, eased);
    this.camera.fov = THREE.MathUtils.lerp(this.startFov, this.targetFov, eased);
    this.camera.updateProjectionMatrix();
    if (linear >= 1) this.transitioning = false;
    return this.transitioning;
  }

  cancel(): void {
    this.transitioning = false;
  }

  isTransitioning(): boolean {
    return this.transitioning;
  }
}
