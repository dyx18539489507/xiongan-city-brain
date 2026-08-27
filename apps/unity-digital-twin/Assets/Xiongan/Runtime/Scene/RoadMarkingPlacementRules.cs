using System.Collections.Generic;
using System.Linq;
using UnityEngine;

namespace Xiongan.DigitalTwin.Scene
{
    public static class RoadMarkingPlacementRules
    {
        public static string NormaliseDirections(IEnumerable<string> source)
        {
            return new string(source
                .SelectMany(value => value.ToLowerInvariant())
                .Where(value => value is 'l' or 's' or 'r')
                .Distinct()
                .OrderBy(DirectionOrder)
                .ToArray());
        }

        public static string SelectDisplayDirections(IEnumerable<string> source)
        {
            var directions = NormaliseDirections(source);
            // A three-headed glyph becomes an indistinct paint blot at WebGL
            // viewing distance. SUMO keeps every connection; the road surface
            // shows the dominant through movement for that fully shared lane.
            return directions == "lsr" ? "s" : directions;
        }

        public static bool TryResolveArrow(
            IReadOnlyList<Vector3> points,
            out Vector3 position,
            out Vector3 forward)
        {
            position = Vector3.zero;
            forward = Vector3.forward;
            if (points.Count < 2) return false;
            var totalLength = 0f;
            for (var index = 1; index < points.Count; index++)
            {
                var segment = points[index] - points[index - 1];
                segment.y = 0f;
                totalLength += segment.magnitude;
            }
            if (totalLength < 17f) return false;

            var preferred = Mathf.Clamp(totalLength * 0.22f, 12f, 22f);
            var distanceFromEnd = Mathf.Clamp(preferred, 12f, totalLength - 4f);
            var remaining = distanceFromEnd;
            for (var index = points.Count - 1; index > 0; index--)
            {
                var segment = points[index] - points[index - 1];
                segment.y = 0f;
                var length = segment.magnitude;
                if (length < 0.05f) continue;
                forward = segment / length;
                if (remaining <= length)
                {
                    position = points[index] - forward * remaining;
                    return true;
                }
                remaining -= length;
            }
            return false;
        }

        private static int DirectionOrder(char direction)
        {
            return direction switch
            {
                'l' => 0,
                's' => 1,
                'r' => 2,
                _ => 3,
            };
        }
    }
}
