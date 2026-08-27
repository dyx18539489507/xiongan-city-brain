import {TwinIcon, type TwinIconName} from "./twin/TwinIcon";

export type PlatformWorkspace = "simulation" | "algorithms" | "scenarios";

type Props = {
  active: PlatformWorkspace;
  onChange: (workspace: PlatformWorkspace) => void;
};

const items: Array<{id: PlatformWorkspace; icon: TwinIconName; label: string}> = [
  {id: "simulation", icon: "route", label: "仿真指挥"},
  {id: "algorithms", icon: "activity", label: "算法评估"},
  {id: "scenarios", icon: "map", label: "场景生成"},
];

export function PlatformWorkspaceNav({active, onChange}: Props) {
  return (
    <nav aria-label="平台工作区" className="platform-workspace-nav">
      <button className="platform-wordmark" onClick={() => onChange("simulation")}>
        <span>雄安城市大脑</span>
        <b>车路云协同管控平台</b>
      </button>
      <div className="platform-workspace-tabs">
        {items.map((item) => (
          <button
            aria-current={active === item.id ? "page" : undefined}
            className={active === item.id ? "active" : ""}
            key={item.id}
            onClick={() => onChange(item.id)}
          >
            <TwinIcon name={item.icon} />
            <span>{item.label}</span>
          </button>
        ))}
      </div>
    </nav>
  );
}
