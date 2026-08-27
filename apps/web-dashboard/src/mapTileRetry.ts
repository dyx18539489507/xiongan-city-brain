const autonaviSubdomains = ["1", "2", "3", "4"] as const;

export function buildMapTileRetryUrls(primaryUrl: string, fallbackUrl: string): string[] {
  const match = primaryUrl.match(/webrd0([1-4])/i);
  if (!match) return Array.from(new Set([primaryUrl, fallbackUrl]));

  const current = match[1];
  const orderedSubdomains = [current, ...autonaviSubdomains.filter((subdomain) => subdomain !== current)];
  const autonaviUrls = orderedSubdomains.map((subdomain) => (
    primaryUrl.replace(/webrd0[1-4]/i, `webrd0${subdomain}`)
  ));
  return Array.from(new Set([...autonaviUrls, fallbackUrl]));
}
