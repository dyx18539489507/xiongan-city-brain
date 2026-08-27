using System.Collections.Generic;
using System.Linq;
using UnityEngine;

namespace Xiongan.DigitalTwin.Scene
{
    public readonly struct ReferenceShowcaseFrame
    {
        public ReferenceShowcaseFrame(Vector3 center, Vector3 forward)
        {
            Center = center;
            Forward = Vector3.ProjectOnPlane(forward, Vector3.up).normalized;
            if (Forward.sqrMagnitude < 0.5f) Forward = Vector3.forward;
            Right = Vector3.Cross(Vector3.up, Forward).normalized;
        }

        public Vector3 Center { get; }
        public Vector3 Forward { get; }
        public Vector3 Right { get; }
        public float CameraYaw => Mathf.Atan2(Forward.x, Forward.z) * Mathf.Rad2Deg;

        public Vector3 Point(float across, float height, float along) =>
            Center + Right * across + Vector3.up * height + Forward * along;

        public List<Vector3> Rectangle(
            float across, float along, float width, float depth, float height = 0f)
        {
            var center = Point(across, height, along);
            var halfRight = Right * (width * 0.5f);
            var halfForward = Forward * (depth * 0.5f);
            return new List<Vector3>
            {
                center - halfRight - halfForward,
                center + halfRight - halfForward,
                center + halfRight + halfForward,
                center - halfRight + halfForward,
            };
        }
    }

    public static class ReferenceShowcaseLayout
    {
        public const string JunctionId = "cluster_10739806290_13007678851_13007678852_9999059766";
        public const string DisplayId = "B01";
        public const float LongitudinalTransitionStart = 126f;
        public const float LongitudinalTransitionEnd = 220f;
        public const float CrossTransitionStart = 112f;
        public const float CrossTransitionEnd = 205f;
        public const float LongitudinalMotorHalfWidth = 26f;
        public const float CrossMotorHalfWidth = 25f;
        public const float TransitionMotorHalfWidth = 11.5f;
        public const float LongitudinalSurfaceHalfWidth = 34.5f;
        public const float CrossSurfaceHalfWidth = 33.5f;
        public const float TransitionSurfaceHalfWidth = 17.5f;
        private const float RoadsideDeviceAcross = 118f;
        private const float RoadsideDeviceAlong = 29.4f;

        public static ReferenceShowcaseFrame Resolve(SceneBuilder scene)
        {
            var junction = scene.Document.Junctions.First(item => item.SumoJunctionId == JunctionId);
            var center = scene.Coordinates.ToWorld(junction.Position);
            var approaches = scene.Document.Lanes
                .Where(lane => lane.EdgeFunction != "internal" &&
                               lane.LaneKind is "motor" or "mixed" &&
                               lane.Shape.Count >= 2)
                .Select(lane =>
                {
                    var end = scene.Coordinates.ToWorld(lane.Shape[^1]);
                    var previous = scene.Coordinates.ToWorld(lane.Shape[^2]);
                    var forward = Vector3.ProjectOnPlane(end - previous, Vector3.up).normalized;
                    return new
                    {
                        Forward = forward,
                        Distance = Vector3.Distance(end, center),
                        Heading = Mathf.RoundToInt(
                            Mathf.Repeat(Mathf.Atan2(forward.x, forward.z) * Mathf.Rad2Deg, 360f) / 15f),
                    };
                })
                .Where(item => item.Distance < 52f && item.Forward.sqrMagnitude > 0.5f)
                .GroupBy(item => item.Heading)
                .OrderByDescending(group => group.Count())
                .FirstOrDefault();
            var mainForward = approaches == null
                ? new Vector3(-0.9490495f, 0f, 0.3151272f)
                : approaches.Aggregate(Vector3.zero, (sum, item) => sum + item.Forward).normalized;
            return new ReferenceShowcaseFrame(center, mainForward);
        }

        public static bool CoversRoadMarkingOverride(
            ReferenceShowcaseFrame frame, Vector3 point)
        {
            return CoversRoadSurfaceOverride(frame, point, -0.5f);
        }

        public static Vector2 ToLocal(ReferenceShowcaseFrame frame, Vector3 point)
        {
            var relative = Vector3.ProjectOnPlane(point - frame.Center, Vector3.up);
            return new Vector2(
                Vector3.Dot(relative, frame.Right),
                Vector3.Dot(relative, frame.Forward));
        }

        public static bool CoversRoadSurfaceOverride(
            ReferenceShowcaseFrame frame, Vector3 point, float margin = 0f)
        {
            var local = ToLocal(frame, point);
            var across = Mathf.Abs(local.x);
            var along = Mathf.Abs(local.y);
            return along <= LongitudinalTransitionEnd + margin &&
                   across <= ResolveHalfWidth(
                       along,
                       LongitudinalTransitionStart,
                       LongitudinalTransitionEnd,
                       LongitudinalSurfaceHalfWidth,
                       TransitionSurfaceHalfWidth) + margin ||
                   across <= CrossTransitionEnd + margin &&
                   along <= ResolveHalfWidth(
                       across,
                       CrossTransitionStart,
                       CrossTransitionEnd,
                       CrossSurfaceHalfWidth,
                       TransitionSurfaceHalfWidth) + margin;
        }

        public static bool CoversMotorCarriageway(
            ReferenceShowcaseFrame frame, Vector3 point, float margin = 0f)
        {
            var local = ToLocal(frame, point);
            var across = Mathf.Abs(local.x);
            var along = Mathf.Abs(local.y);
            return along <= LongitudinalTransitionEnd + margin &&
                   across <= ResolveLongitudinalMotorHalfWidth(along) + margin ||
                   across <= CrossTransitionEnd + margin &&
                   along <= ResolveCrossMotorHalfWidth(across) + margin;
        }

        public static float ResolveLongitudinalMotorHalfWidth(float along) =>
            ResolveHalfWidth(
                Mathf.Abs(along),
                LongitudinalTransitionStart,
                LongitudinalTransitionEnd,
                LongitudinalMotorHalfWidth,
                TransitionMotorHalfWidth);

        public static float ResolveCrossMotorHalfWidth(float across) =>
            ResolveHalfWidth(
                Mathf.Abs(across),
                CrossTransitionStart,
                CrossTransitionEnd,
                CrossMotorHalfWidth,
                TransitionMotorHalfWidth);

        public static float ResolveMotorLaneScale(float distance, bool longitudinal)
        {
            var fullWidth = longitudinal ? LongitudinalMotorHalfWidth : CrossMotorHalfWidth;
            var halfWidth = longitudinal
                ? ResolveLongitudinalMotorHalfWidth(distance)
                : ResolveCrossMotorHalfWidth(distance);
            return halfWidth / fullWidth;
        }

        private static float ResolveHalfWidth(
            float distance, float transitionStart, float transitionEnd,
            float fullHalfWidth, float endHalfWidth)
        {
            var progress = Mathf.InverseLerp(transitionStart, transitionEnd, distance);
            return Mathf.Lerp(fullHalfWidth, endHalfWidth, progress);
        }

        public static bool IsSignalPoleOnInnerFootwayEdge(
            ReferenceShowcaseFrame frame, Vector3 point)
        {
            var local = ToLocal(frame, point);
            var across = Mathf.Abs(local.x);
            var along = Mathf.Abs(local.y);
            var longitudinalCorner =
                across >= 26.8f && across <= 27.9f &&
                along >= 36f && along <= 37f;
            var crossCorner =
                across >= 37f && across <= 38f &&
                along >= 25.8f && along <= 26.9f;
            return longitudinalCorner || crossCorner;
        }

        public static bool IsSignalPoleOnFarSide(
            ReferenceShowcaseFrame frame, Vector3 point, Vector3 approachForward)
        {
            var direction = Vector3.ProjectOnPlane(approachForward, Vector3.up).normalized;
            if (direction.sqrMagnitude < 0.5f) return false;
            var relative = Vector3.ProjectOnPlane(point - frame.Center, Vector3.up);
            return Vector3.Dot(relative, direction) >= 35.5f;
        }

        public static bool IntersectsRoadSurfaceOverride(
            ReferenceShowcaseFrame frame, IReadOnlyList<Vector3> points, float margin = 0f)
        {
            for (var index = 0; index < points.Count - 1; index++)
            {
                var from = points[index];
                var to = points[index + 1];
                var distance = Vector3.Distance(from, to);
                var samples = Mathf.Max(1, Mathf.CeilToInt(distance / 8f));
                for (var sample = 0; sample <= samples; sample++)
                    if (CoversRoadSurfaceOverride(
                            frame, Vector3.Lerp(from, to, sample / (float)samples), margin))
                        return true;
            }
            return points.Count == 1 && CoversRoadSurfaceOverride(frame, points[0], margin);
        }

        public static Vector3 ResolveRoadsideDevicePosition(
            ReferenceShowcaseFrame frame, string deviceType)
        {
            var across = deviceType == "camera" ? -RoadsideDeviceAcross : RoadsideDeviceAcross;
            return frame.Point(across, 0f, RoadsideDeviceAlong);
        }

        public static bool IsRoadsideDeviceOnOuterFootway(
            ReferenceShowcaseFrame frame, Vector3 point)
        {
            var relative = Vector3.ProjectOnPlane(point - frame.Center, Vector3.up);
            var across = Mathf.Abs(Vector3.Dot(relative, frame.Right));
            var along = Vector3.Dot(relative, frame.Forward);
            return across >= 108f && across <= 128f &&
                   Mathf.Abs(along - RoadsideDeviceAlong) <= 3.2f;
        }
    }
}
