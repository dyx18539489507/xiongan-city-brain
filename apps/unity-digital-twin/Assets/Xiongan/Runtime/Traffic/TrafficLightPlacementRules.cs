using System;
using System.Collections.Generic;
using UnityEngine;
using Xiongan.DigitalTwin.Scene;

namespace Xiongan.DigitalTwin.Traffic
{
    public readonly struct SignalApproachLane
    {
        public SignalApproachLane(
            string laneId, int linkIndex, Vector3 stopPoint, Vector3 forward, float width)
        {
            LaneId = laneId;
            LinkIndex = linkIndex;
            StopPoint = stopPoint;
            Forward = forward;
            Width = width;
        }

        public string LaneId { get; }
        public int LinkIndex { get; }
        public Vector3 StopPoint { get; }
        public Vector3 Forward { get; }
        public float Width { get; }
    }

    public readonly struct SignalApproachPlacement
    {
        public SignalApproachPlacement(Vector3 polePosition, Vector3 forward, Vector3 trafficRight)
        {
            PolePosition = polePosition;
            Forward = forward;
            TrafficRight = trafficRight;
        }

        public Vector3 PolePosition { get; }
        public Vector3 Forward { get; }
        public Vector3 TrafficRight { get; }
    }

    public readonly struct PedestrianFaceDirections
    {
        public PedestrianFaceDirections(Vector3 acrossCrossing, Vector3 alongCrossing)
        {
            AcrossCrossing = acrossCrossing;
            AlongCrossing = alongCrossing;
        }

        public Vector3 AcrossCrossing { get; }
        public Vector3 AlongCrossing { get; }
    }

    public static class TrafficLightPlacementRules
    {
        private static readonly float[] SidewalkOffsets =
            { 1.05f, 1.45f, 1.95f, 2.65f, 3.55f, 4.75f, 6.25f, 8.5f, 11.5f };
        private static readonly float[] UpstreamOffsets =
            { 0.75f, 1.35f, 2.25f, 3.5f, 5.25f, 7f, 9.5f, 12.5f };

        public static SignalApproachPlacement Resolve(
            IReadOnlyList<SignalApproachLane> lanes,
            Func<Vector3, bool>? isBlocked = null)
        {
            if (lanes.Count == 0) throw new ArgumentException("At least one approach lane is required.", nameof(lanes));

            var forward = Vector3.zero;
            var center = Vector3.zero;
            foreach (var lane in lanes)
            {
                var laneForward = Vector3.ProjectOnPlane(lane.Forward, Vector3.up).normalized;
                if (laneForward.sqrMagnitude > 0.5f) forward += laneForward;
                center += lane.StopPoint;
            }
            forward.Normalize();
            if (forward.sqrMagnitude < 0.5f)
                forward = Vector3.ProjectOnPlane(lanes[0].Forward, Vector3.up).normalized;
            if (forward.sqrMagnitude < 0.5f) forward = Vector3.forward;
            center /= lanes.Count;

            // ToWorld mirrors SUMO Y into Unity Z, so SUMO traffic-right is
            // forward x up rather than Unity transform.right.
            var trafficRight = Vector3.Cross(forward, Vector3.up).normalized;
            var rightmost = lanes[0];
            var rightmostProjection = float.NegativeInfinity;
            foreach (var lane in lanes)
            {
                var projection = Vector3.Dot(lane.StopPoint - center, trafficRight) + lane.Width * 0.5f;
                if (projection <= rightmostProjection) continue;
                rightmost = lane;
                rightmostProjection = projection;
            }

            var carriagewayEdge = rightmost.StopPoint + trafficRight * Mathf.Max(1.1f, rightmost.Width * 0.5f);
            if (isBlocked == null)
                return new SignalApproachPlacement(
                    carriagewayEdge + trafficRight * SidewalkOffsets[0] - forward * UpstreamOffsets[0],
                    forward,
                    trafficRight);

            var best = Vector3.zero;
            var found = false;
            var bestCost = float.PositiveInfinity;
            foreach (var sidewalkOffset in SidewalkOffsets)
            {
                foreach (var upstreamOffset in UpstreamOffsets)
                {
                    var candidate = carriagewayEdge + trafficRight * sidewalkOffset - forward * upstreamOffset;
                    if (isBlocked(candidate)) continue;
                    var cost = sidewalkOffset + upstreamOffset * 0.32f;
                    if (cost >= bestCost) continue;
                    best = candidate;
                    bestCost = cost;
                    found = true;
                }
            }

            if (!found)
                throw new InvalidOperationException(
                    $"No road-clear signal pole position exists for approach lane {lanes[0].LaneId}.");

            return new SignalApproachPlacement(best, forward, trafficRight);
        }

        public static SignalApproachPlacement ResolveShowcase(
            ReferenceShowcaseFrame frame,
            IReadOnlyList<SignalApproachLane> lanes)
        {
            if (lanes.Count == 0)
                throw new ArgumentException("At least one approach lane is required.", nameof(lanes));

            var forward = Vector3.zero;
            foreach (var lane in lanes)
                forward += Vector3.ProjectOnPlane(lane.Forward, Vector3.up).normalized;
            forward.Normalize();
            if (forward.sqrMagnitude < 0.5f)
                forward = Vector3.ProjectOnPlane(lanes[0].Forward, Vector3.up).normalized;
            if (forward.sqrMagnitude < 0.5f) forward = frame.Forward;

            var directions = new[] { frame.Forward, -frame.Forward, frame.Right, -frame.Right };
            var bestDirection = 0;
            var bestDot = float.NegativeInfinity;
            for (var index = 0; index < directions.Length; index++)
            {
                var dot = Vector3.Dot(forward, directions[index]);
                if (dot <= bestDot) continue;
                bestDot = dot;
                bestDirection = index;
            }

            // B01 has a deliberately widened presentation boulevard that no longer
            // shares the source SUMO kerb geometry. Each pole sits on the far-side
            // footway corner so its face is visible across the junction.
            var polePosition = bestDirection switch
            {
                0 => frame.Point(27.35f, 0f, 36.5f),
                1 => frame.Point(-27.35f, 0f, -36.5f),
                2 => frame.Point(37.5f, 0f, -26.35f),
                _ => frame.Point(-37.5f, 0f, 26.35f),
            };
            return new SignalApproachPlacement(
                polePosition,
                forward,
                Vector3.Cross(Vector3.up, forward).normalized);
        }

        public static float ResolveHeadOffset(
            IReadOnlyList<SignalApproachLane> lanes,
            Vector3 polePosition,
            Vector3 forward,
            float minimumReach,
            float maximumReach)
        {
            if (lanes.Count == 0)
                throw new ArgumentException("At least one approach lane is required.", nameof(lanes));
            if (minimumReach <= 0f || maximumReach < minimumReach)
                throw new ArgumentOutOfRangeException(nameof(minimumReach));

            var localRight = Vector3.Cross(Vector3.up,
                Vector3.ProjectOnPlane(forward, Vector3.up).normalized);
            if (localRight.sqrMagnitude < 0.5f) localRight = Vector3.right;
            var average = 0f;
            foreach (var lane in lanes)
                average += Vector3.Dot(lane.StopPoint - polePosition, localRight);
            average /= lanes.Count;

            var direction = Mathf.Abs(average) < 0.01f ? 1f : Mathf.Sign(average);
            return direction * Mathf.Clamp(Mathf.Abs(average), minimumReach, maximumReach);
        }

        public static PedestrianFaceDirections ResolvePedestrianFaceDirections(
            SignalApproachPlacement placement)
        {
            var forward = Vector3.ProjectOnPlane(placement.Forward, Vector3.up).normalized;
            if (forward.sqrMagnitude < 0.5f) forward = Vector3.forward;
            var trafficRight = Vector3.ProjectOnPlane(placement.TrafficRight, Vector3.up).normalized;
            if (trafficRight.sqrMagnitude < 0.5f)
                trafficRight = Vector3.Cross(Vector3.up, forward).normalized;

            // Showcase poles sit on the far-side corner for their arriving
            // approach. Pedestrians on the opposite kerb therefore see the two
            // faces looking back across the junction, not away from it.
            return new PedestrianFaceDirections(-trafficRight, -forward);
        }

        public static float DistanceToSegmentXZ(Vector3 point, Vector3 from, Vector3 to)
        {
            var delta = to - from;
            delta.y = 0f;
            var relative = point - from;
            relative.y = 0f;
            var denominator = delta.sqrMagnitude;
            if (denominator < 0.0001f) return relative.magnitude;
            var amount = Mathf.Clamp01(Vector3.Dot(relative, delta) / denominator);
            return (relative - delta * amount).magnitude;
        }

        public static bool PointInPolygonXZ(Vector3 point, IReadOnlyList<Vector3> polygon)
        {
            if (polygon.Count < 3) return false;
            var inside = false;
            for (int current = 0, previous = polygon.Count - 1;
                 current < polygon.Count;
                 previous = current++)
            {
                var a = polygon[current];
                var b = polygon[previous];
                var crosses = (a.z > point.z) != (b.z > point.z) &&
                              point.x < (b.x - a.x) * (point.z - a.z) /
                              (b.z - a.z) + a.x;
                if (crosses) inside = !inside;
            }
            return inside;
        }
    }
}
