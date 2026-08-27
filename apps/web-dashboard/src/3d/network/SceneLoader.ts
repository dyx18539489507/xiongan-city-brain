import {assertStaticScene, type StaticSceneDocument} from "../scene/types";

export type SceneLoadProgress = {
  stage: "download" | "parse" | "ready";
  loadedBytes: number;
  totalBytes: number | null;
};

type PendingScene = {
  promise: Promise<StaticSceneDocument>;
  progress: SceneLoadProgress;
  listeners: Set<(progress: SceneLoadProgress) => void>;
};

const sceneDocuments = new Map<string, StaticSceneDocument>();
const pendingScenes = new Map<string, PendingScene>();

function aborted(): DOMException {
  return new DOMException("scene request aborted", "AbortError");
}

function waitForScene(pending: PendingScene, signal: AbortSignal, onProgress: (progress: SceneLoadProgress) => void): Promise<StaticSceneDocument> {
  if (signal.aborted) return Promise.reject(aborted());
  pending.listeners.add(onProgress);
  onProgress(pending.progress);
  return new Promise((resolve, reject) => {
    const cleanup = () => {
      signal.removeEventListener("abort", handleAbort);
      pending.listeners.delete(onProgress);
    };
    const handleAbort = () => { cleanup(); reject(aborted()); };
    signal.addEventListener("abort", handleAbort, {once: true});
    pending.promise.then(
      (document) => { cleanup(); resolve(document); },
      (reason: unknown) => { cleanup(); reject(reason); },
    );
  });
}

async function fetchStaticScene(
  scenarioId: string,
  onProgress: (progress: SceneLoadProgress) => void,
): Promise<StaticSceneDocument> {
  const response = await fetch(`/api/v1/scenes/${encodeURIComponent(scenarioId)}/3d`, {
    headers: {Accept: "application/json"},
  });
  if (!response.ok) throw new Error(`scene request failed: HTTP ${response.status}`);
  const totalHeader = response.headers.get("content-length");
  const totalBytes = totalHeader && !response.headers.get("content-encoding") ? Number(totalHeader) : null;
  const reader = response.body?.getReader();
  if (!reader) {
    onProgress({stage: "parse", loadedBytes: 0, totalBytes});
    const payload: unknown = await response.json();
    assertStaticScene(payload, scenarioId);
    onProgress({stage: "ready", loadedBytes: totalBytes ?? 0, totalBytes});
    return payload;
  }

  const decoder = new TextDecoder();
  let jsonText = "";
  let loadedBytes = 0;
  while (true) {
    const {done, value} = await reader.read();
    if (done) break;
    jsonText += decoder.decode(value, {stream: true});
    loadedBytes += value.byteLength;
    onProgress({stage: "download", loadedBytes, totalBytes});
  }
  jsonText += decoder.decode();
  onProgress({stage: "parse", loadedBytes, totalBytes});
  const payload: unknown = JSON.parse(jsonText);
  assertStaticScene(payload, scenarioId);
  onProgress({stage: "ready", loadedBytes, totalBytes});
  return payload;
}

export function loadStaticScene(
  scenarioId: string,
  signal: AbortSignal,
  onProgress: (progress: SceneLoadProgress) => void,
): Promise<StaticSceneDocument> {
  const cached = sceneDocuments.get(scenarioId);
  if (cached) {
    if (signal.aborted) return Promise.reject(aborted());
    onProgress({stage: "ready", loadedBytes: 0, totalBytes: null});
    return Promise.resolve(cached);
  }

  let pending = pendingScenes.get(scenarioId);
  if (!pending) {
    const listeners = new Set<(progress: SceneLoadProgress) => void>();
    let entry!: PendingScene;
    const promise = fetchStaticScene(scenarioId, (progress) => {
      entry.progress = progress;
      entry.listeners.forEach((listener) => listener(progress));
    }).then((document) => {
      sceneDocuments.set(scenarioId, document);
      pendingScenes.delete(scenarioId);
      return document;
    }).catch((reason: unknown) => {
      pendingScenes.delete(scenarioId);
      throw reason;
    });
    entry = {
      progress: {stage: "download", loadedBytes: 0, totalBytes: null},
      listeners,
      promise,
    };
    pending = entry;
    pendingScenes.set(scenarioId, entry);
  }
  return waitForScene(pending, signal, onProgress);
}
