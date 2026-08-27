const algorithmMetadata: Record<string, {code: string; label: string; order: number}> = {
  "fixed-time": {code: "B0", label: "固定配时控制", order: 0},
  "actuated-control": {code: "B1", label: "感应控制", order: 1},
  "max-pressure": {code: "B2", label: "最大压力控制", order: 2},
  "coordinated-max-pressure": {code: "B3", label: "协同最大压力控制", order: 3},
};

export function algorithmLabel(name: string | null | undefined): string {
  if (!name) return "未知算法";
  return algorithmMetadata[name]?.label ?? name;
}

export function algorithmOptionLabel(name: string): string {
  const metadata = algorithmMetadata[name];
  return metadata ? `${metadata.code} · ${metadata.label}` : name;
}

export function sortAlgorithms<T extends {name: string}>(items: readonly T[]): T[] {
  return [...items].sort((left, right) => {
    const leftOrder = algorithmMetadata[left.name]?.order ?? Number.MAX_SAFE_INTEGER;
    const rightOrder = algorithmMetadata[right.name]?.order ?? Number.MAX_SAFE_INTEGER;
    return leftOrder - rightOrder || algorithmLabel(left.name).localeCompare(algorithmLabel(right.name), "zh-CN");
  });
}
