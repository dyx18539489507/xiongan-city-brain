import type {ReactNode, SVGProps} from "react";

export type TwinIconName = "play" | "pause" | "stop" | "reset" | "layers" | "chevron" | "map" | "route" | "focus" | "plus" | "minus" | "warning" | "activity" | "cloud" | "signal" | "timeline" | "expand" | "close" | "car" | "settings" | "lock";

const paths: Record<TwinIconName, ReactNode> = {
  play: <path d="m8 5 11 7-11 7Z" />,
  pause: <><path d="M8 5v14" /><path d="M16 5v14" /></>,
  stop: <rect x="6" y="6" width="12" height="12" rx="2" />,
  reset: <><path d="M3 12a9 9 0 1 0 3-6.7" /><path d="M3 4v6h6" /></>,
  layers: <><path d="m12 2 9 5-9 5-9-5Z" /><path d="m3 12 9 5 9-5" /><path d="m3 17 9 5 9-5" /></>,
  chevron: <path d="m9 18 6-6-6-6" />,
  map: <><path d="m3 6 6-3 6 3 6-3v15l-6 3-6-3-6 3Z" /><path d="M9 3v15M15 6v15" /></>,
  route: <><circle cx="6" cy="19" r="2" /><circle cx="18" cy="5" r="2" /><path d="M8 19h3a4 4 0 0 0 4-4v-6a4 4 0 0 1 3-4" /></>,
  focus: <><path d="M8 3H5a2 2 0 0 0-2 2v3M16 3h3a2 2 0 0 1 2 2v3M8 21H5a2 2 0 0 1-2-2v-3M16 21h3a2 2 0 0 0 2-2v-3" /><circle cx="12" cy="12" r="3" /></>,
  plus: <><path d="M12 5v14" /><path d="M5 12h14" /></>,
  minus: <path d="M5 12h14" />,
  warning: <><path d="M10.3 3.6 2.2 18a2 2 0 0 0 1.8 3h16a2 2 0 0 0 1.8-3L13.7 3.6a2 2 0 0 0-3.4 0Z" /><path d="M12 9v4M12 17h.01" /></>,
  activity: <path d="M3 12h4l2-7 4 14 2-7h6" />,
  cloud: <path d="M17.5 19H7a5 5 0 1 1 1.2-9.8A6.5 6.5 0 0 1 20 12.5 3.5 3.5 0 0 1 17.5 19Z" />,
  signal: <><rect x="8" y="2" width="8" height="20" rx="4" /><circle cx="12" cy="7" r="1.5" /><circle cx="12" cy="12" r="1.5" /><circle cx="12" cy="17" r="1.5" /></>,
  timeline: <><path d="M3 12h18" /><circle cx="8" cy="12" r="2" /><circle cx="17" cy="12" r="2" /></>,
  expand: <><path d="M8 3H3v5M16 3h5v5M8 21H3v-5M16 21h5v-5" /></>,
  close: <><path d="m6 6 12 12" /><path d="m18 6-12 12" /></>,
  car: <><path d="m5 11 2-5h10l2 5" /><rect x="3" y="11" width="18" height="7" rx="2" /><path d="M7 18v2M17 18v2" /></>,
  settings: <><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6v.2h-4V21a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1L4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9A1.7 1.7 0 0 0 3 14H2.8v-4H3a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9L4.2 7 7 4.2l.1.1a1.7 1.7 0 0 0 1.9.3A1.7 1.7 0 0 0 10 3V2.8h4V3a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1L19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1h.2v4H21a1.7 1.7 0 0 0-1.6 1Z" /></>,
  lock: <><rect x="5" y="10" width="14" height="11" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3" /></>,
};

export function TwinIcon({name, ...props}: {name: TwinIconName} & SVGProps<SVGSVGElement>) {
  return <svg aria-hidden="true" fill="none" height="20" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" viewBox="0 0 24 24" width="20" {...props}>{paths[name]}</svg>;
}
