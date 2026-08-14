import * as THREE from "three";
import type {CoordinateService} from "../core/CoordinateService";
import type {StaticSceneDocument} from "../scene/types";
import {MaterialManager} from "../scene/MaterialManager";
import {CrossingGeometryBuilder} from "./CrossingGeometryBuilder";
import {JunctionGeometryBuilder} from "./JunctionGeometryBuilder";
import {LaneGeometryBuilder} from "./LaneGeometryBuilder";
import {RoadMarkingBuilder} from "./RoadMarkingBuilder";

export type RoadBuildStats = {
  laneTriangles: number;
  junctionTriangles: number;
  crossingTriangles: number;
  markingTriangles: number;
  stopLines: number;
  drawObjects: number;
};

export type RoadBuildStage = "junctions" | "lanes" | "crossings" | "markings";

export class RoadGeometryBuilder {
  constructor(
    private readonly coordinates: CoordinateService,
    private readonly materials: MaterialManager,
  ) {}

  build(scene: StaticSceneDocument): {root: THREE.Group; stats: RoadBuildStats} {
    const root = new THREE.Group();
    root.name = "XionganConnected20RoadNetwork";
    const junctions = new JunctionGeometryBuilder(this.coordinates, this.materials).build(
      scene.junctions,
    );
    const lanes = new LaneGeometryBuilder(this.coordinates, this.materials).build(
      scene.lanes,
      scene.edges,
      scene.coordinateSystem.sceneBounds,
    );
    const crossings = new CrossingGeometryBuilder(this.coordinates, this.materials).build(
      scene.crossings,
    );
    const markings = new RoadMarkingBuilder(this.coordinates, this.materials).build(
      scene.lanes,
      scene.edges,
      new Set(scene.junctions.filter((item) => item.controlled).map((item) => item.sumoJunctionId)),
      scene.coordinateSystem.sceneBounds,
    );
    root.add(junctions.mesh, lanes.group, crossings.group, markings.mesh);
    return {
      root,
      stats: {
        laneTriangles: lanes.triangles,
        junctionTriangles: junctions.triangles,
        crossingTriangles: crossings.triangles,
        markingTriangles: markings.triangles,
        stopLines: markings.stopLines,
        drawObjects: root.children.length + lanes.group.children.length + crossings.group.children.length,
      },
    };
  }

  async buildStaged(
    scene: StaticSceneDocument,
    yieldControl: () => Promise<void>,
    onStage: (stage: RoadBuildStage) => void,
  ): Promise<{root: THREE.Group; stats: RoadBuildStats}> {
    const root = new THREE.Group();
    root.name = "XionganConnected20RoadNetwork";

    onStage("junctions");
    const junctions = new JunctionGeometryBuilder(this.coordinates, this.materials).build(
      scene.junctions,
    );
    root.add(junctions.mesh);
    await yieldControl();

    onStage("lanes");
    const lanes = new LaneGeometryBuilder(this.coordinates, this.materials).build(
      scene.lanes,
      scene.edges,
      scene.coordinateSystem.sceneBounds,
    );
    root.add(lanes.group);
    await yieldControl();

    onStage("crossings");
    const crossings = new CrossingGeometryBuilder(this.coordinates, this.materials).build(
      scene.crossings,
    );
    root.add(crossings.group);
    await yieldControl();

    onStage("markings");
    const markings = new RoadMarkingBuilder(this.coordinates, this.materials).build(
      scene.lanes,
      scene.edges,
      new Set(scene.junctions.filter((item) => item.controlled).map((item) => item.sumoJunctionId)),
      scene.coordinateSystem.sceneBounds,
    );
    root.add(markings.mesh);
    return {
      root,
      stats: {
        laneTriangles: lanes.triangles,
        junctionTriangles: junctions.triangles,
        crossingTriangles: crossings.triangles,
        markingTriangles: markings.triangles,
        stopLines: markings.stopLines,
        drawObjects: root.children.length + lanes.group.children.length + crossings.group.children.length,
      },
    };
  }
}
