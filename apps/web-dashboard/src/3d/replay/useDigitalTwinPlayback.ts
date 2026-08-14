import {useCallback, useEffect, useMemo, useRef, useState} from "react";
import {useDigitalTwinStream} from "../network/DigitalTwinSocket";
import {emptyDigitalTwinState} from "../network/DigitalTwinStore";
import type {DigitalTwinState, DigitalTwinStream} from "../network/digitalTwinTypes";
import {ReplayManager, type ReplaySnapshot} from "./ReplayManager";

export type DigitalTwinMode = "live" | "replay";

export type ReplayItem = {
  experimentId: string;
  scenarioId: string;
  simulationTimeS: number;
  status: string;
  frameCount: number;
  bytes: number;
  url: string;
  algorithm?: string | null;
  profile?: string | null;
  seed?: number | null;
  summaryMetrics?: Record<string, number | string | boolean | null>;
  actualRun?: boolean;
};

export type DigitalTwinPlayback = {
  stream: DigitalTwinStream;
  mode: DigitalTwinMode;
  replays: ReplayItem[];
  selectedReplayId: string | null;
  replay: ReplaySnapshot;
  replayBusy: boolean;
  replayIssue: string | null;
  refreshReplays: () => Promise<void>;
  loadReplay: (experimentId: string) => Promise<void>;
  goLive: () => void;
  toggleReplay: () => void;
  setReplaySpeed: (speed: number) => void;
  seekReplay: (simulationTimeS: number) => void;
  stepReplay: () => void;
};

const emptyReplaySnapshot: ReplaySnapshot = {
  loaded: false,
  playing: false,
  speed: 1,
  currentTimeS: 0,
  durationS: 0,
  frameIndex: -1,
  frameCount: 0,
};

export function useDigitalTwinPlayback(): DigitalTwinPlayback {
  const [mode, setMode] = useState<DigitalTwinMode>("live");
  const live = useDigitalTwinStream(mode === "live");
  const managerRef = useRef(new ReplayManager());
  const [replays, setReplays] = useState<ReplayItem[]>([]);
  const [selectedReplayId, setSelectedReplayId] = useState<string | null>(null);
  const [replayState, setReplayState] = useState<DigitalTwinState>(emptyDigitalTwinState);
  const [replay, setReplay] = useState<ReplaySnapshot>(emptyReplaySnapshot);
  const [replayBusy, setReplayBusy] = useState(false);
  const [replayIssue, setReplayIssue] = useState<string | null>(null);

  const refreshReplays = useCallback(async () => {
    const response = await fetch("/api/v1/replays", {cache: "no-store"});
    if (!response.ok) throw new Error(`Replay inventory failed: ${response.status}`);
    const payload = (await response.json()) as {items?: ReplayItem[]};
    const items = Array.isArray(payload.items) ? payload.items : [];
    setReplays(items);
    setSelectedReplayId((current) =>
      current && items.some((item) => item.experimentId === current)
        ? current
        : (items[0]?.experimentId ?? null),
    );
  }, []);

  useEffect(() => {
    refreshReplays().catch((reason: unknown) => {
      setReplayIssue(reason instanceof Error ? reason.message : String(reason));
    });
  }, [refreshReplays]);

  useEffect(() => {
    if (mode !== "replay") return;
    let animationFrame = 0;
    let previous = performance.now();
    const animate = (now: number) => {
      const manager = managerRef.current;
      const before = manager.snapshot();
      const nextState = manager.advance((now - previous) / 1000);
      const after = manager.snapshot();
      previous = now;
      if (after.frameIndex !== before.frameIndex || after.playing !== before.playing) {
        setReplayState(nextState);
        setReplay(after);
      }
      animationFrame = window.requestAnimationFrame(animate);
    };
    animationFrame = window.requestAnimationFrame(animate);
    return () => window.cancelAnimationFrame(animationFrame);
  }, [mode]);

  const loadReplay = useCallback(
    async (experimentId: string) => {
      const item = replays.find((candidate) => candidate.experimentId === experimentId);
      if (!item) throw new Error("Replay is no longer available");
      setReplayBusy(true);
      setReplayIssue(null);
      try {
        const state = await managerRef.current.load(item.url);
        setSelectedReplayId(experimentId);
        setReplayState(state);
        setReplay(managerRef.current.snapshot());
        setMode("replay");
      } catch (reason: unknown) {
        const issue = reason instanceof Error ? reason.message : String(reason);
        setReplayIssue(issue);
        throw reason;
      } finally {
        setReplayBusy(false);
      }
    },
    [replays],
  );

  const goLive = useCallback(() => {
    managerRef.current.pause();
    setReplay(managerRef.current.snapshot());
    setMode("live");
  }, []);

  const toggleReplay = useCallback(() => {
    const manager = managerRef.current;
    const current = manager.snapshot();
    if (current.playing) manager.pause();
    else manager.play();
    setReplay(manager.snapshot());
  }, []);

  const setReplaySpeed = useCallback((speed: number) => {
    managerRef.current.setSpeed(speed);
    setReplay(managerRef.current.snapshot());
  }, []);

  const seekReplay = useCallback((simulationTimeS: number) => {
    const state = managerRef.current.seek(simulationTimeS);
    setReplayState(state);
    setReplay(managerRef.current.snapshot());
  }, []);

  const stepReplay = useCallback(() => {
    const state = managerRef.current.step();
    setReplayState(state);
    setReplay(managerRef.current.snapshot());
  }, []);

  const stream = useMemo<DigitalTwinStream>(
    () =>
      mode === "live"
        ? live
        : {
            connection: replayState.initialized ? "online" : "offline",
            state: replayState,
            issue: replayIssue,
          },
    [live, mode, replayIssue, replayState],
  );

  return {
    stream,
    mode,
    replays,
    selectedReplayId,
    replay,
    replayBusy,
    replayIssue,
    refreshReplays,
    loadReplay,
    goLive,
    toggleReplay,
    setReplaySpeed,
    seekReplay,
    stepReplay,
  };
}
