import {
  applyDigitalTwinMessage,
  emptyDigitalTwinState,
  parseDigitalTwinMessage,
} from "../network/DigitalTwinStore";
import type {DigitalTwinMessage, DigitalTwinState} from "../network/digitalTwinTypes";

export type ReplaySnapshot = {
  loaded: boolean;
  playing: boolean;
  speed: number;
  currentTimeS: number;
  durationS: number;
  frameIndex: number;
  frameCount: number;
};

const MAX_REPLAY_BYTES = 100 * 1024 * 1024;
const MAX_REPLAY_FRAMES = 120_000;

export class ReplayManager {
  private frames: DigitalTwinMessage[] = [];
  private state: DigitalTwinState = emptyDigitalTwinState;
  private cursor = -1;
  private playing = false;
  private speed = 1;
  private durationS = 0;
  private playheadS = 0;

  async load(url: string): Promise<DigitalTwinState> {
    const response = await fetch(url, {cache: "no-store"});
    if (!response.ok) throw new Error(`Replay load failed: ${response.status}`);
    const declaredBytes = Number(response.headers.get("content-length") ?? 0);
    if (declaredBytes > MAX_REPLAY_BYTES) throw new Error("Replay exceeds 100 MB limit");
    if (!response.body) return this.loadText(await response.text());
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    const parsed: DigitalTwinMessage[] = [];
    let pending = "";
    let bytes = 0;
    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      bytes += value.byteLength;
      if (bytes > MAX_REPLAY_BYTES) {
        await reader.cancel();
        throw new Error("Replay exceeds 100 MB limit");
      }
      pending += decoder.decode(value, {stream: true});
      const lines = pending.split(/\r?\n/);
      pending = lines.pop() ?? "";
      for (const line of lines) this.parseLine(line, parsed);
    }
    pending += decoder.decode();
    this.parseLine(pending, parsed);
    return this.loadFrames(parsed);
  }

  loadText(text: string): DigitalTwinState {
    if (new TextEncoder().encode(text).byteLength > MAX_REPLAY_BYTES) {
      throw new Error("Replay exceeds 100 MB limit");
    }
    const parsed: DigitalTwinMessage[] = [];
    for (const line of text.split(/\r?\n/)) {
      if (!line.trim()) continue;
      parsed.push(parseDigitalTwinMessage(JSON.parse(line) as unknown));
      if (parsed.length > MAX_REPLAY_FRAMES) {
        throw new Error("Replay exceeds 120000 frame limit");
      }
    }
    return this.loadFrames(parsed);
  }

  private parseLine(line: string, parsed: DigitalTwinMessage[]): void {
    if (!line.trim()) return;
    parsed.push(parseDigitalTwinMessage(JSON.parse(line) as unknown));
    if (parsed.length > MAX_REPLAY_FRAMES) {
      throw new Error("Replay exceeds 120000 frame limit");
    }
  }

  private loadFrames(parsed: DigitalTwinMessage[]): DigitalTwinState {
    if (!parsed.length || parsed[0]?.type !== "init") {
      throw new Error("Replay must start with an init snapshot");
    }
    this.frames = parsed;
    this.durationS = Math.max(...parsed.map((frame) => frame.simulationTimeS));
    this.pause();
    return this.seek(0);
  }

  play(speed = this.speed): void {
    this.setSpeed(speed);
    this.playing = true;
  }

  pause(): void {
    this.playing = false;
  }

  setSpeed(speed: number): void {
    if (!Number.isFinite(speed) || speed <= 0 || speed > 16) {
      throw new Error("Replay speed must be within (0, 16]");
    }
    this.speed = speed;
  }

  advance(realDeltaSeconds: number): DigitalTwinState {
    if (!this.playing || !this.frames.length) return this.state;
    this.playheadS = Math.min(
      this.durationS,
      this.playheadS + Math.max(0, realDeltaSeconds) * this.speed,
    );
    this.applyUntil(this.playheadS);
    if (this.playheadS >= this.durationS) this.playing = false;
    return this.state;
  }

  step(): DigitalTwinState {
    this.applyNext();
    this.playheadS = this.state.simulationTimeS;
    return this.state;
  }

  seek(simulationTimeS: number): DigitalTwinState {
    if (!this.frames.length) throw new Error("Replay is not loaded");
    const target = Math.min(this.durationS, Math.max(0, simulationTimeS));
    this.state = emptyDigitalTwinState;
    this.cursor = -1;
    // Always materialize the init snapshot so the shared renderer has a scene
    // reference even when the requested time precedes the first SUMO frame.
    this.applyNext();
    this.applyUntil(target);
    this.playheadS = Math.max(target, this.state.simulationTimeS);
    return this.state;
  }

  currentState(): DigitalTwinState {
    return this.state;
  }

  snapshot(): ReplaySnapshot {
    return {
      loaded: this.frames.length > 0,
      playing: this.playing,
      speed: this.speed,
      currentTimeS: this.playheadS,
      durationS: this.durationS,
      frameIndex: this.cursor,
      frameCount: this.frames.length,
    };
  }

  private applyUntil(target: number): void {
    while (
      this.cursor + 1 < this.frames.length &&
      (this.frames[this.cursor + 1]?.simulationTimeS ?? Number.POSITIVE_INFINITY) <= target
    ) {
      this.applyNext();
    }
  }

  private applyNext(): void {
    if (this.cursor + 1 >= this.frames.length) return;
    this.cursor += 1;
    this.state = applyDigitalTwinMessage(this.state, this.frames[this.cursor]!);
  }
}
