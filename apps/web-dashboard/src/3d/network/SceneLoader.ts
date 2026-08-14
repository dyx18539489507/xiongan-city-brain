import {assertStaticScene, type StaticSceneDocument} from "../scene/types";

export type SceneLoadProgress = {
  stage: "download" | "parse" | "ready";
  loadedBytes: number;
  totalBytes: number | null;
};

export async function loadStaticScene(
  scenarioId: string,
  signal: AbortSignal,
  onProgress: (progress: SceneLoadProgress) => void,
): Promise<StaticSceneDocument> {
  const response = await fetch(`/api/v1/scenes/${encodeURIComponent(scenarioId)}/3d`, {
    signal,
    headers: {Accept: "application/json"},
  });
  if (!response.ok) throw new Error(`scene request failed: HTTP ${response.status}`);
  const totalHeader = response.headers.get("content-length");
  const totalBytes = totalHeader && !response.headers.get("content-encoding") ? Number(totalHeader) : null;
  const reader = response.body?.getReader();
  if (!reader) {
    onProgress({stage: "parse", loadedBytes: 0, totalBytes});
    const payload: unknown = await response.json();
    assertStaticScene(payload);
    onProgress({stage: "ready", loadedBytes: totalBytes ?? 0, totalBytes});
    return payload;
  }

  const chunks: Uint8Array[] = [];
  let loadedBytes = 0;
  while (true) {
    const {done, value} = await reader.read();
    if (done) break;
    chunks.push(value);
    loadedBytes += value.byteLength;
    onProgress({stage: "download", loadedBytes, totalBytes});
  }
  const merged = new Uint8Array(loadedBytes);
  let offset = 0;
  for (const chunk of chunks) {
    merged.set(chunk, offset);
    offset += chunk.byteLength;
  }
  onProgress({stage: "parse", loadedBytes, totalBytes});
  const payload: unknown = JSON.parse(new TextDecoder().decode(merged));
  assertStaticScene(payload);
  onProgress({stage: "ready", loadedBytes, totalBytes});
  return payload;
}
