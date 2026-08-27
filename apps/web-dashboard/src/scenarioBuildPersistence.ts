import type {ScenarioBuildRecord} from "./api";

export function selectRestorableScenarioBuild(
  builds: ScenarioBuildRecord[],
  preferredId: string | null,
): ScenarioBuildRecord | null {
  const completed = builds.filter((build) => build.status === "completed" && Boolean(build.result));
  return completed.find((build) => build.id === preferredId) ?? completed[0] ?? null;
}
