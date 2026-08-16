import {useEffect, useState} from "react";
import {loadStaticScene} from "../3d/network/SceneLoader";
import type {StaticSceneDocument} from "../3d/scene/types";
import type {SceneLoadState} from "./model";

const initialLoadState: SceneLoadState = {
  status: "loading",
  message: "正在读取 SUMO 场景几何",
  loadedBytes: 0,
  totalBytes: null,
};

/** Load the immutable SUMO-derived scene once per selected scenario. */
export function useStaticScene(scenarioId: string) {
  const [scene, setScene] = useState<StaticSceneDocument | null>(null);
  const [loadState, setLoadState] = useState<SceneLoadState>(initialLoadState);

  useEffect(() => {
    const controller = new AbortController();
    setScene(null);
    setLoadState(initialLoadState);
    loadStaticScene(scenarioId, controller.signal, (progress) => {
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
          message: reason instanceof Error ? reason.message : String(reason),
          loadedBytes: 0,
          totalBytes: null,
        });
      });
    return () => controller.abort();
  }, [scenarioId]);

  return {scene, loadState};
}
