using System;
using System.Collections.Generic;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace Xiongan.DigitalTwin.Data
{
    [Serializable]
    public sealed class Point2
    {
        [JsonProperty("x")] public float X;
        [JsonProperty("y")] public float Y;
    }

    [Serializable]
    public sealed class SceneMetadata
    {
        [JsonProperty("schemaVersion")] public string SchemaVersion = string.Empty;
        [JsonProperty("sceneId")] public string SceneId = string.Empty;
        [JsonProperty("scenarioId")] public string ScenarioId = string.Empty;
        [JsonProperty("claimBoundary")] public string ClaimBoundary = string.Empty;
        [JsonProperty("counts")] public Dictionary<string, int> Counts = new();
    }

    [Serializable]
    public sealed class CoordinateSystemRecord
    {
        [JsonProperty("worldOriginSumo")] public Point2 WorldOriginSumo = new();
    }

    [Serializable]
    public sealed class JunctionRecord
    {
        [JsonProperty("sceneId")] public string SceneId = string.Empty;
        [JsonProperty("sumoJunctionId")] public string SumoJunctionId = string.Empty;
        [JsonProperty("position")] public Point2 Position = new();
        [JsonProperty("shape")] public List<Point2> Shape = new();
        [JsonProperty("controlled")] public bool Controlled;
        [JsonProperty("displayId")] public string? DisplayId;
        [JsonProperty("displayName")] public string? DisplayName;
    }

    [Serializable]
    public sealed class LaneRecord
    {
        [JsonProperty("sceneId")] public string SceneId = string.Empty;
        [JsonProperty("sumoLaneId")] public string SumoLaneId = string.Empty;
        [JsonProperty("sumoEdgeId")] public string SumoEdgeId = string.Empty;
        [JsonProperty("edgeFunction")] public string? EdgeFunction;
        [JsonProperty("laneKind")] public string LaneKind = "motor";
        [JsonProperty("shape")] public List<Point2> Shape = new();
        [JsonProperty("widthM")] public float WidthM = 3.2f;
    }

    [Serializable]
    public sealed class ConnectionRecord
    {
        [JsonProperty("fromLaneId")] public string FromLaneId = string.Empty;
        [JsonProperty("toLaneId")] public string ToLaneId = string.Empty;
        [JsonProperty("direction")] public string Direction = string.Empty;
        [JsonProperty("tlsId")] public string? TlsId;
        [JsonProperty("linkIndex")] public int? LinkIndex;
    }

    [Serializable]
    public sealed class CrossingRecord
    {
        [JsonProperty("sceneId")] public string SceneId = string.Empty;
        [JsonProperty("junctionId")] public string JunctionId = string.Empty;
        [JsonProperty("shape")] public List<Point2> Shape = new();
        [JsonProperty("widthM")] public float WidthM = 4f;
    }

    [Serializable]
    public sealed class SignalLinkRecord
    {
        [JsonProperty("linkIndex")] public int LinkIndex;
        [JsonProperty("fromLaneId")] public string FromLaneId = string.Empty;
        [JsonProperty("toLaneId")] public string ToLaneId = string.Empty;
        [JsonProperty("viaLaneId")] public string? ViaLaneId;
    }

    [Serializable]
    public sealed class TrafficLightRecord
    {
        [JsonProperty("sumoTlsId")] public string SumoTlsId = string.Empty;
        [JsonProperty("controlledJunctionId")] public string ControlledJunctionId = string.Empty;
        [JsonProperty("links")] public List<SignalLinkRecord> Links = new();
        [JsonProperty("displayId")] public string DisplayId = string.Empty;
    }

    [Serializable]
    public sealed class AreaRecord
    {
        [JsonProperty("sceneId")] public string SceneId = string.Empty;
        [JsonProperty("areaType")] public string AreaType = string.Empty;
        [JsonProperty("shape")] public List<Point2> Shape = new();
    }

    [Serializable]
    public sealed class BuildingRecord
    {
        [JsonProperty("sceneId")] public string SceneId = string.Empty;
        [JsonProperty("buildingType")] public string BuildingType = string.Empty;
        [JsonProperty("footprint")] public List<Point2> Footprint = new();
        [JsonProperty("heightM")] public float? HeightM;
        [JsonProperty("levels")] public float? Levels;
    }

    [Serializable]
    public sealed class RoadsideDeviceRecord
    {
        [JsonProperty("deviceId")] public string DeviceId = string.Empty;
        [JsonProperty("deviceType")] public string DeviceType = string.Empty;
        [JsonProperty("position")] public Point2 Position = new();
        [JsonProperty("communicationStatus")] public string CommunicationStatus = string.Empty;
        [JsonProperty("provenance")] public string Provenance = string.Empty;
        [JsonProperty("managedJunctions")] public List<string> ManagedJunctions = new();
    }

    [Serializable]
    public sealed class SceneDocument
    {
        [JsonProperty("metadata")] public SceneMetadata Metadata = new();
        [JsonProperty("coordinateSystem")] public CoordinateSystemRecord CoordinateSystem = new();
        [JsonProperty("junctions")] public List<JunctionRecord> Junctions = new();
        [JsonProperty("lanes")] public List<LaneRecord> Lanes = new();
        [JsonProperty("connections")] public List<ConnectionRecord> Connections = new();
        [JsonProperty("crossings")] public List<CrossingRecord> Crossings = new();
        [JsonProperty("trafficLights")] public List<TrafficLightRecord> TrafficLights = new();
        [JsonProperty("pedestrianAreas")] public List<AreaRecord> PedestrianAreas = new();
        [JsonProperty("bicycleAreas")] public List<AreaRecord> BicycleAreas = new();
        [JsonProperty("buildings")] public List<BuildingRecord> Buildings = new();
        [JsonProperty("vegetation")] public List<AreaRecord> Vegetation = new();
        [JsonProperty("zones")] public List<AreaRecord> Zones = new();
        [JsonProperty("roadsideDevices")] public List<RoadsideDeviceRecord> RoadsideDevices = new();
    }

    [Serializable]
    public sealed class VehicleEntity
    {
        [JsonProperty("id")] public string Id = string.Empty;
        [JsonProperty("type")] public string Type = string.Empty;
        [JsonProperty("vehicleClass")] public string VehicleClass = string.Empty;
        [JsonProperty("x")] public float X;
        [JsonProperty("y")] public float Y;
        [JsonProperty("angle")] public float Angle;
        [JsonProperty("speed")] public float Speed;
        [JsonProperty("acceleration")] public float Acceleration;
        [JsonProperty("laneId")] public string LaneId = string.Empty;
        [JsonProperty("edgeId")] public string EdgeId = string.Empty;
        [JsonProperty("signals")] public int Signals;
        [JsonProperty("color")] public string Color = string.Empty;
        [JsonProperty("brake")] public bool Brake;
        [JsonProperty("status")] public string Status = string.Empty;
    }

    [Serializable]
    public sealed class PedestrianEntity
    {
        [JsonProperty("id")] public string Id = string.Empty;
        [JsonProperty("x")] public float X;
        [JsonProperty("y")] public float Y;
        [JsonProperty("angle")] public float Angle;
        [JsonProperty("speed")] public float Speed;
        [JsonProperty("laneId")] public string LaneId = string.Empty;
        [JsonProperty("edgeId")] public string EdgeId = string.Empty;
        [JsonProperty("status")] public string Status = string.Empty;
    }

    [Serializable]
    public sealed class TrafficLightEntity
    {
        [JsonProperty("id")] public string Id = string.Empty;
        [JsonProperty("phaseIndex")] public int PhaseIndex;
        [JsonProperty("state")] public string State = string.Empty;
        [JsonProperty("phaseDurationS")] public float PhaseDurationS;
        [JsonProperty("remainingS")] public float RemainingS;
    }

    [Serializable]
    public sealed class ConflictEntity
    {
        [JsonProperty("id")] public string Id = string.Empty;
        [JsonProperty("x")] public float X;
        [JsonProperty("y")] public float Y;
        [JsonProperty("severity")] public string Severity = string.Empty;
        [JsonProperty("ttcS")] public float? TtcS;
        [JsonProperty("petS")] public float? PetS;
    }

    [Serializable]
    public sealed class RealtimeEvent
    {
        [JsonProperty("eventId")] public string EventId = string.Empty;
        [JsonProperty("simulationTime")] public float SimulationTime;
        [JsonProperty("event")] public string Event = string.Empty;
        [JsonProperty("detail")] public string? Detail;
        [JsonProperty("payload")] public JObject Payload = new();
    }

    [Serializable]
    public sealed class EntitySet
    {
        [JsonProperty("vehicles")] public List<VehicleEntity> Vehicles = new();
        [JsonProperty("bicycles")] public List<VehicleEntity> Bicycles = new();
        [JsonProperty("pedestrians")] public List<PedestrianEntity> Pedestrians = new();
    }

    [Serializable]
    public sealed class RemovalSet
    {
        [JsonProperty("vehicles")] public List<string> Vehicles = new();
        [JsonProperty("bicycles")] public List<string> Bicycles = new();
        [JsonProperty("pedestrians")] public List<string> Pedestrians = new();
    }

    [Serializable]
    public sealed class DigitalTwinInit
    {
        [JsonProperty("protocolVersion")] public string ProtocolVersion = string.Empty;
        [JsonProperty("sequence")] public long Sequence;
        [JsonProperty("experimentId")] public string? ExperimentId;
        [JsonProperty("scenarioId")] public string ScenarioId = string.Empty;
        [JsonProperty("simulationTimeS")] public float SimulationTimeS;
        [JsonProperty("tickHz")] public float TickHz = 1f;
        [JsonProperty("entities")] public EntitySet Entities = new();
        [JsonProperty("trafficLights")] public List<TrafficLightEntity> TrafficLights = new();
        [JsonProperty("conflicts")] public List<ConflictEntity> Conflicts = new();
        [JsonProperty("activeEvents")] public List<RealtimeEvent> ActiveEvents = new();
        [JsonProperty("metrics")] public JObject Metrics = new();
    }

    [Serializable]
    public sealed class DigitalTwinDelta
    {
        [JsonProperty("protocolVersion")] public string ProtocolVersion = string.Empty;
        [JsonProperty("sequence")] public long Sequence;
        [JsonProperty("experimentId")] public string ExperimentId = string.Empty;
        [JsonProperty("simulationTimeS")] public float SimulationTimeS;
        [JsonProperty("spawn")] public EntitySet Spawn = new();
        [JsonProperty("update")] public EntitySet Update = new();
        [JsonProperty("remove")] public RemovalSet Remove = new();
        [JsonProperty("trafficLights")] public List<TrafficLightEntity> TrafficLights = new();
        [JsonProperty("conflicts")] public List<ConflictEntity> Conflicts = new();
        [JsonProperty("events")] public List<RealtimeEvent> Events = new();
        [JsonProperty("metrics")] public JObject Metrics = new();
    }

    [Serializable]
    public sealed class BrowserSnapshot
    {
        [JsonProperty("sequence")] public long Sequence;
        [JsonProperty("experimentId")] public string? ExperimentId;
        [JsonProperty("simulationTimeS")] public float SimulationTimeS;
        [JsonProperty("tickHz")] public float TickHz = 1f;
        [JsonProperty("entities")] public EntitySet Entities = new();
        [JsonProperty("trafficLights")] public List<TrafficLightEntity> TrafficLights = new();
        [JsonProperty("conflicts")] public List<ConflictEntity> Conflicts = new();
        [JsonProperty("events")] public List<RealtimeEvent> Events = new();
        [JsonProperty("metrics")] public JObject Metrics = new();
    }
}
