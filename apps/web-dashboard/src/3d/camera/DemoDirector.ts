import type {WeatherMode} from "../environment/WeatherManager";

export type DemoView =
  | "overview"
  | "corridor"
  | "urban"
  | "vehicles"
  | "multimodal"
  | "pedestrians"
  | "events"
  | "rsu"
  | "monitor"
  | "driver"
  | "cruise"
  | "junction";

export type DemoCue = {
  atS: number;
  label: string;
  view: DemoView;
  junctionId?: string;
  weather?: WeatherMode;
  displayMode?: "real" | "analysis";
};

export type DemoTimeline = {
  id: string;
  durationS: number;
  cues: DemoCue[];
};

export type DemoSnapshot = {
  running: boolean;
  elapsedS: number;
  durationS: number;
  cueIndex: number;
  label: string;
};

export class DemoDirector {
  private running = false;
  private elapsedS = 0;
  private cueIndex = -1;

  constructor(
    private readonly timeline: DemoTimeline,
    private readonly onCue: (cue: DemoCue) => void,
  ) {
    if (timeline.durationS <= 0 || !timeline.cues.length) {
      throw new Error("Demo timeline must contain a positive duration and cues");
    }
    for (let index = 0; index < timeline.cues.length; index += 1) {
      const cue = timeline.cues[index]!;
      if (cue.atS < 0 || cue.atS > timeline.durationS) {
        throw new Error("Demo cue falls outside the timeline");
      }
      if (index > 0 && cue.atS <= timeline.cues[index - 1]!.atS) {
        throw new Error("Demo cues must be strictly ordered");
      }
    }
  }

  start(): DemoSnapshot {
    this.running = true;
    this.elapsedS = 0;
    this.cueIndex = -1;
    this.applyDueCues();
    return this.snapshot();
  }

  stop(): DemoSnapshot {
    this.running = false;
    return this.snapshot();
  }

  update(deltaS: number): DemoSnapshot {
    if (!this.running) return this.snapshot();
    this.elapsedS = Math.min(
      this.timeline.durationS,
      this.elapsedS + Math.max(0, deltaS),
    );
    this.applyDueCues();
    if (this.elapsedS >= this.timeline.durationS) this.running = false;
    return this.snapshot();
  }

  snapshot(): DemoSnapshot {
    return {
      running: this.running,
      elapsedS: this.elapsedS,
      durationS: this.timeline.durationS,
      cueIndex: this.cueIndex,
      label: this.cueIndex >= 0 ? this.timeline.cues[this.cueIndex]!.label : "待机",
    };
  }

  private applyDueCues(): void {
    while (
      this.cueIndex + 1 < this.timeline.cues.length &&
      this.timeline.cues[this.cueIndex + 1]!.atS <= this.elapsedS
    ) {
      this.cueIndex += 1;
      this.onCue(this.timeline.cues[this.cueIndex]!);
    }
  }
}
