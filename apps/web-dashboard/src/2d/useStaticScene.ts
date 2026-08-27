import {useCallback, useEffect, useState} from "react";
import {describeRequestError} from "../api";
import {loadStaticScene} from "../3d/network/SceneLoader";
import type {StaticSceneDocument} from "../3d/scene/types";
import type {SceneLoadState} from "./model";

const initialLoadState: SceneLoadState = {
  status: "loading",
  message: "正在读取 SUMO 场景几何",
  loadedBytes: 0,
  totalBytes: null,
};

const sceneDocuments = new Map<string, StaticSceneDocument>();
const sceneRequests = new Map<string, Promise<StaticSceneDocument>>();

function cachedSceneRequest(
  scenarioId: string,
  _signal: AbortSignal,
  progress: Parameters<typeof loadStaticScene>[2],
): Promise<StaticSceneDocument> {
  const cached = sceneDocuments.get(scenarioId);
  if (cached) return Promise.resolve(cached);
  const pending = sceneRequests.get(scenarioId);
  if (pending) return pending;
  // The request is shared across consumers, so a single unmount must not
  // cancel parsing for the other map or a later remount.
  const request = loadStaticScene(scenarioId, new AbortController().signal, progress)
    .then((document) => {
      sceneDocuments.set(scenarioId, document);
      return document;
    })
    .finally(() => sceneRequests.delete(scenarioId));
  sceneRequests.set(scenarioId, request);
  return request;
}

/** Load the immutable SUMO-derived scene once per selected scenario. */
export function useStaticScene(scenarioId: string) {
  const [scene, setScene] = useState<StaticSceneDocument | null>(null);
  const [loadState, setLoadState] = useState<SceneLoadState>(initialLoadState);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const reload = useCallback(() => setLoadAttempt((current) => current + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    setScene(null);
    setLoadState(initialLoadState);
    cachedSceneRequest(scenarioId, controller.signal, (progress) => {
      const message =
        progress.stage === "download"
          ? "正在下载 SUMO 场景几何"
          : progress.stage === "parse"
            ? "正在建立车道与路口索引"
            : "SUMO 场景几何已就绪";
      setLoadState({
        status: progress.stage === "ready" ? "ready" : "loading",
        message,
        loadedBytes: progress.loadedBytes,
        totalBytes: progress.totalBytes,
      });
    })
      .then((document) => setScene(document))
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        setLoadState({
          status: "error",
          message: describeRequestError(reason),
          loadedBytes: 0,
          totalBytes: null,
        });
      });
    return () => controller.abort();
  }, [loadAttempt, scenarioId]);

  return {scene, loadState, reload};
}
