import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const outputDir = path.resolve("outputs/official_20_audit");
const audit = JSON.parse(
  await fs.readFile(path.join(outputDir, "official_20_audit.json"), "utf8"),
);

const workbook = Workbook.create();
const overview = workbook.worksheets.add("Overview");
const intersections = workbook.worksheets.add("Intersections");
const profiles = workbook.worksheets.add("Profiles");
const geometry = workbook.worksheets.add("Geometry");
const issues = workbook.worksheets.add("Source Issues");

const palette = {
  navy: "#0C1424",
  navy2: "#17243A",
  teal: "#1E9E8F",
  tealLight: "#DDF3EF",
  gold: "#F4CF57",
  red: "#C84A52",
  redLight: "#FBE3E5",
  green: "#287A64",
  greenLight: "#DDF1E8",
  gray: "#5B6470",
  grayLight: "#F2F4F7",
  white: "#FFFFFF",
  border: "#D5DBE3",
};

function titleBlock(sheet, title, subtitle, lastColumn) {
  sheet.showGridLines = false;
  sheet.mergeCells(`A1:${lastColumn}2`);
  sheet.getRange(`A1:${lastColumn}2`).values = [[title]];
  sheet.getRange(`A1:${lastColumn}2`).format = {
    fill: palette.navy,
    font: { color: palette.white, bold: true, size: 20 },
    verticalAlignment: "center",
    horizontalAlignment: "left",
    wrapText: true,
  };
  sheet.mergeCells(`A3:${lastColumn}3`);
  sheet.getRange(`A3:${lastColumn}3`).values = [[subtitle]];
  sheet.getRange(`A3:${lastColumn}3`).format = {
    fill: palette.navy2,
    font: { color: "#DDE8F3", size: 10 },
    verticalAlignment: "center",
    wrapText: true,
  };
  sheet.getRange("1:3").format.rowHeight = 27;
}

function tableHeader(range) {
  range.format = {
    fill: palette.teal,
    font: { color: palette.white, bold: true, size: 10 },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    wrapText: true,
    borders: { preset: "all", style: "thin", color: palette.border },
  };
  range.format.rowHeight = 34;
}

function tableBody(range) {
  range.format = {
    font: { color: "#243040", size: 9 },
    verticalAlignment: "center",
    wrapText: true,
    borders: { preset: "all", style: "thin", color: palette.border },
  };
  range.format.rowHeight = 28;
}

function paintBoolean(sheet, rowNumber, columnLetter, value) {
  const cell = sheet.getRange(`${columnLetter}${rowNumber}`);
  cell.format.fill = value ? palette.greenLight : palette.redLight;
  cell.format.font = { color: value ? palette.green : palette.red, bold: true };
  cell.format.horizontalAlignment = "center";
}

titleBlock(
  overview,
  "官方20个独立路口 · SUMO数据一致性审计",
  "1—4号参考主办方SUMO示例；5—20号为主办方Excel/PNG + OSM工程模型。未清空结果如实保留。",
  "H",
);
overview.getRange("A5:D5").values = [["检查门", "实际值", "目标/基准", "判定"]];
tableHeader(overview.getRange("A5:D5"));
const kpiLabels = [
  "独立路口工程",
  "主办方SUMO示例参考",
  "车道配置可追溯",
  "15分钟流量逐项一致",
  "信号分量逐项一致",
  "黄色/simple shapes/300ms",
  "SUMO正常退出",
  "需求守恒",
  "9000秒内完全清空",
  "碰撞",
  "瞬移",
];
overview.getRange("A6:A16").values = kpiLabels.map((value) => [value]);
overview.getRange("C6:C16").values = [[20], [4], [20], [60], [60], [60], [60], [60], [60], [0], [0]];
overview.getRange("B6:B16").formulas = [
  ["=COUNTA(Intersections!A6:A25)"],
  ["=SUM(Intersections!C6:C25)"],
  ["=SUM(Intersections!H6:H25)"],
  ["=SUM(Profiles!E6:E65)"],
  ["=SUM(Profiles!F6:F65)"],
  ["=SUM(Profiles!G6:G65)"],
  ["=COUNTIF(Profiles!Q6:Q65,0)"],
  ["=SUM(Profiles!M6:M65)"],
  ["=SUM(Profiles!N6:N65)"],
  ["=SUM(Profiles!O6:O65)"],
  ["=SUM(Profiles!P6:P65)"],
];
overview.getRange("D6:D16").formulas = Array.from({ length: 11 }, (_, index) => [
  index === 8 ? '="结果记录"' : `=IF(B${index + 6}=C${index + 6},"通过","需复核")`,
]);
tableBody(overview.getRange("A6:D16"));
for (let row = 6; row <= 16; row += 1) {
  const pass = row === 14 || audit.summary[
    [
      "intersection_count",
      "official_sumo_reference_count",
      "lane_configuration_traceable_count",
      "flow_interval_exact_count",
      "signal_components_exact_count",
      "theme_gui_exact_count",
      "sumo_exit_ok_count",
      "demand_conservation_count",
      "cleared_profile_count",
      "collision_count",
      "teleport_count",
    ][row - 6]
  ] === [20, 4, 20, 60, 60, 60, 60, 60, 60, 0, 0][row - 6];
  overview.getRange(`D${row}`).format.fill = row === 14 ? "#FFF4CC" : pass ? palette.greenLight : palette.redLight;
  overview.getRange(`D${row}`).format.font = {
    color: row === 14 ? "#806000" : pass ? palette.green : palette.red,
    bold: true,
  };
  overview.getRange(`D${row}`).format.horizontalAlignment = "center";
}
overview.mergeCells("F5:H5");
overview.getRange("F5:H5").values = [["证据边界与发现"]];
tableHeader(overview.getRange("F5:H5"));
overview.mergeCells("F6:H9");
overview.getRange("F6:H9").values = [[audit.summary.evidence_boundary]];
overview.mergeCells("F10:H12");
overview.getRange("F10:H12").values = [[
  `主办方Excel内部：${audit.summary.workbook_source_consistent_count}/20工作簿完全一致；${audit.summary.organizer_source_issue_count}个字段级差异。执行以8行15分钟流量和逐相位绿/黄/全红分量为准。`,
]];
overview.mergeCells("F13:H16");
overview.getRange("F13:H16").values = [[
  `道路证据共${audit.summary.geometry_arm_count}条臂；1—4号保留主办方SUMO长度，5—20号共${audit.summary.geometry_adjustment_count}条道路臂统一采用250m独立路口边界。OSM证据长度与模型长度分别保留。`,
]];
tableBody(overview.getRange("F6:H16"));
overview.getRange("A5:H16").format.borders = { preset: "all", style: "thin", color: palette.border };
overview.getRange("A:A").format.columnWidth = 26;
overview.getRange("B:D").format.columnWidth = 14;
overview.getRange("E:E").format.columnWidth = 3;
overview.getRange("F:H").format.columnWidth = 20;

titleBlock(
  intersections,
  "20个路口总表",
  "车道登记表精确匹配18/20；13、14号为显式人工复核覆盖，仍可追溯但需后续图资校准。",
  "M",
);
const intersectionHeaders = [
  "路口", "来源分类", "官方SUMO参考", "车道证据方法", "置信度", "登记表精确匹配",
  "配置状态", "配置可追溯", "Excel内部一致", "几何调整数", "结构有效", "清空时段数", "备注",
];
intersections.getRange("A5:M5").values = [intersectionHeaders];
tableHeader(intersections.getRange("A5:M5"));
const intersectionRows = audit.intersections.map((row) => [
  row.demo_id,
  row.provenance_class,
  row.official_sumo_reference ? 1 : 0,
  row.lane_evidence_method,
  row.lane_confidence,
  row.lane_counts_match_evidence ? 1 : 0,
  row.lane_configuration_status,
  row.lane_configuration_traceable ? 1 : 0,
  row.workbook_source_consistent ? 1 : 0,
  row.geometry_adjustment_count,
  row.structurally_valid ? 1 : 0,
  row.profiles_cleared,
  row.demo_id <= 4 ? "主办方示例几何/车道" : "PNG/OSM工程模型",
]);
intersections.getRangeByIndexes(5, 0, intersectionRows.length, intersectionHeaders.length).values = intersectionRows;
tableBody(intersections.getRange("A6:M25"));
for (let index = 0; index < audit.intersections.length; index += 1) {
  const rowNumber = index + 6;
  paintBoolean(intersections, rowNumber, "C", audit.intersections[index].official_sumo_reference);
  paintBoolean(intersections, rowNumber, "F", audit.intersections[index].lane_counts_match_evidence);
  paintBoolean(intersections, rowNumber, "H", audit.intersections[index].lane_configuration_traceable);
  paintBoolean(intersections, rowNumber, "I", audit.intersections[index].workbook_source_consistent);
  paintBoolean(intersections, rowNumber, "K", audit.intersections[index].structurally_valid);
}
intersections.freezePanes.freezeRows(5);
intersections.getRange("A:A").format.columnWidth = 8;
intersections.getRange("B:B").format.columnWidth = 35;
intersections.getRange("C:C").format.columnWidth = 14;
intersections.getRange("D:D").format.columnWidth = 30;
intersections.getRange("E:I").format.columnWidth = 15;
intersections.getRange("J:L").format.columnWidth = 12;
intersections.getRange("M:M").format.columnWidth = 24;

titleBlock(
  profiles,
  "60个时段逐项核验",
  "未清空不是生成失败；结构有效、需求守恒和清空状态分别记录。",
  "Q",
);
const profileHeaders = [
  "路口", "时段", "Excel需求", "SUMO需求", "15分钟流量一致", "信号分量一致", "主题/GUI一致",
  "源时段内部一致", "loaded", "完成", "running", "waiting", "需求守恒", "完全清空", "碰撞", "瞬移", "退出码",
];
profiles.getRange("A5:Q5").values = [profileHeaders];
tableHeader(profiles.getRange("A5:Q5"));
const profileRows = audit.profiles.map((row) => [
  row.demo_id, row.profile, row.expected_demand, row.generated_demand, row.flow_intervals_exact ? 1 : 0,
  row.signal_components_exact ? 1 : 0, row.theme_gui_exact ? 1 : 0,
  row.source_profile_consistent ? 1 : 0, row.loaded,
  row.tripinfo_count, row.final_running, row.final_waiting, row.demand_conservation ? 1 : 0,
  row.all_vehicles_cleared ? 1 : 0, row.collisions, row.teleports, row.sumo_exit_code,
]);
profiles.getRangeByIndexes(5, 0, profileRows.length, profileHeaders.length).values = profileRows;
tableBody(profiles.getRange("A6:Q65"));
for (let index = 0; index < audit.profiles.length; index += 1) {
  const rowNumber = index + 6;
  const row = audit.profiles[index];
  paintBoolean(profiles, rowNumber, "E", row.flow_intervals_exact);
  paintBoolean(profiles, rowNumber, "F", row.signal_components_exact);
  paintBoolean(profiles, rowNumber, "G", row.theme_gui_exact);
  paintBoolean(profiles, rowNumber, "H", row.source_profile_consistent);
  paintBoolean(profiles, rowNumber, "M", row.demand_conservation);
  paintBoolean(profiles, rowNumber, "N", row.all_vehicles_cleared);
}
profiles.freezePanes.freezeRows(5);
profiles.getRange("A:B").format.columnWidth = 12;
profiles.getRange("C:D").format.columnWidth = 13;
profiles.getRange("E:H").format.columnWidth = 15;
profiles.getRange("I:Q").format.columnWidth = 11;

titleBlock(
  geometry,
  "道路长度与边界审计",
  "证据长度不覆盖；1—4号保留主办方SUMO长度，5—20号统一采用250m独立路口边界，并保留OSM原始测距与调整类型。",
  "J",
);
const geometryHeaders = [
  "路口", "道路臂", "几何来源", "证据长度(m)", "模型长度(m)", "SUMO进口有效(m)",
  "SUMO出口有效(m)", "调整类型", "长度置信度", "截止依据",
];
geometry.getRange("A5:J5").values = [geometryHeaders];
tableHeader(geometry.getRange("A5:J5"));
const geometryRows = audit.geometry.map((row) => [
  row.demo_id, row.arm, row.geometry_source, row.evidence_length_m, row.modeled_length_m,
  row.sumo_effective_in_m, row.sumo_effective_out_m, row.adjustment_type,
  row.length_confidence, row.cutoff_reason,
]);
geometry.getRangeByIndexes(5, 0, geometryRows.length, geometryHeaders.length).values = geometryRows;
tableBody(geometry.getRange(`A6:J${geometryRows.length + 5}`));
geometry.getRange(`D6:G${geometryRows.length + 5}`).format.numberFormat = "0.00";
for (let index = 0; index < audit.geometry.length; index += 1) {
  if (audit.geometry[index].adjustment_type !== "none") {
    geometry.getRange(`H${index + 6}`).format.fill = "#FFF4CC";
    geometry.getRange(`H${index + 6}`).format.font = { color: "#806000", bold: true };
  }
}
geometry.freezePanes.freezeRows(5);
geometry.getRange("A:B").format.columnWidth = 10;
geometry.getRange("C:C").format.columnWidth = 34;
geometry.getRange("D:G").format.columnWidth = 17;
geometry.getRange("H:J").format.columnWidth = 25;

titleBlock(
  issues,
  "主办方Excel内部差异明细",
  "这些是源表汇总格/比例/周期总计与明细行之间的差异，不是SUMO生成误差；主办方文件未修改。",
  "H",
);
const issueHeaders = ["路口", "时段", "类别", "字段", "源表值", "明细计算值", "显示容差", "差值"];
issues.getRange("A5:H5").values = [issueHeaders];
tableHeader(issues.getRange("A5:H5"));
const issueRows = audit.organizer_source_issues.map((row) => [
  row.demo_id, row.profile, row.category, row.field, row.source, row.calculated,
  row.display_tolerance ?? 0, null,
]);
issues.getRangeByIndexes(5, 0, issueRows.length, issueHeaders.length).values = issueRows;
issues.getRange("H6").formulas = [["=F6-E6"]];
issues.getRange(`H6:H${issueRows.length + 5}`).fillDown();
tableBody(issues.getRange(`A6:H${issueRows.length + 5}`));
issues.getRange(`E6:H${issueRows.length + 5}`).format.numberFormat = "0.0000";
issues.freezePanes.freezeRows(5);
issues.getRange("A:B").format.columnWidth = 12;
issues.getRange("C:D").format.columnWidth = 24;
issues.getRange("E:H").format.columnWidth = 18;

await fs.mkdir(path.join(outputDir, "previews"), { recursive: true });
for (const sheetName of ["Overview", "Intersections", "Profiles", "Geometry", "Source Issues"]) {
  const preview = await workbook.render({
    sheetName,
    autoCrop: "all",
    scale: 0.8,
    format: "png",
  });
  await fs.writeFile(
    path.join(outputDir, "previews", `${sheetName.replaceAll(" ", "_")}.png`),
    new Uint8Array(await preview.arrayBuffer()),
  );
}

for (const [sheetId, range] of [
  ["Overview", "A1:H16"],
  ["Intersections", "A1:M10"],
  ["Profiles", "A1:Q12"],
  ["Geometry", "A1:J12"],
  ["Source Issues", "A1:H12"],
]) {
  const inspection = await workbook.inspect({ kind: "region", sheetId, range, maxChars: 3000 });
  console.log(inspection.ndjson);
}

const formulaErrors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 300 },
  summary: "final formula error scan",
});
console.log(formulaErrors.ndjson);

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(path.join(outputDir, "official_20_data_audit.xlsx"));
console.log(path.join(outputDir, "official_20_data_audit.xlsx"));
