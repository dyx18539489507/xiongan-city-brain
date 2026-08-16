using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Rendering;

namespace Xiongan.DigitalTwin.Scene
{
    public sealed class MeshAccumulator
    {
        private readonly List<Vector3> vertices = new();
        private readonly List<Vector2> uv = new();
        private readonly List<int> triangles = new();

        public int VertexCount => vertices.Count;

        public void AddQuad(Vector3 a, Vector3 b, Vector3 c, Vector3 d)
        {
            AddQuad(a, b, c, d, Vector2.one);
        }

        public void AddQuad(Vector3 a, Vector3 b, Vector3 c, Vector3 d, Vector2 uvScale)
        {
            var start = vertices.Count;
            vertices.Add(a);
            vertices.Add(b);
            vertices.Add(c);
            vertices.Add(d);
            uv.Add(new Vector2(0f, 0f));
            uv.Add(new Vector2(uvScale.x, 0f));
            uv.Add(new Vector2(uvScale.x, uvScale.y));
            uv.Add(new Vector2(0f, uvScale.y));
            triangles.Add(start);
            triangles.Add(start + 1);
            triangles.Add(start + 2);
            triangles.Add(start);
            triangles.Add(start + 2);
            triangles.Add(start + 3);
        }

        public void AddTriangle(Vector3 a, Vector3 b, Vector3 c)
        {
            var start = vertices.Count;
            vertices.Add(a);
            vertices.Add(b);
            vertices.Add(c);
            uv.Add(Vector2.zero);
            uv.Add(Vector2.right);
            uv.Add(Vector2.up);
            triangles.Add(start);
            triangles.Add(start + 1);
            triangles.Add(start + 2);
        }

        public void AddBox(Vector3 center, Vector3 size)
        {
            var half = size * 0.5f;
            var p000 = center + new Vector3(-half.x, -half.y, -half.z);
            var p001 = center + new Vector3(-half.x, -half.y, half.z);
            var p010 = center + new Vector3(-half.x, half.y, -half.z);
            var p011 = center + new Vector3(-half.x, half.y, half.z);
            var p100 = center + new Vector3(half.x, -half.y, -half.z);
            var p101 = center + new Vector3(half.x, -half.y, half.z);
            var p110 = center + new Vector3(half.x, half.y, -half.z);
            var p111 = center + new Vector3(half.x, half.y, half.z);
            AddQuad(p001, p101, p111, p011);
            AddQuad(p100, p000, p010, p110);
            AddQuad(p000, p001, p011, p010);
            AddQuad(p101, p100, p110, p111);
            AddQuad(p010, p011, p111, p110);
            AddQuad(p000, p100, p101, p001);
        }

        public void AddOctahedron(Vector3 center, float radius, float height)
        {
            var top = center + Vector3.up * height * 0.55f;
            var bottom = center - Vector3.up * height * 0.45f;
            var north = center + Vector3.forward * radius;
            var south = center - Vector3.forward * radius;
            var east = center + Vector3.right * radius;
            var west = center - Vector3.right * radius;
            AddTriangle(top, north, east);
            AddTriangle(top, east, south);
            AddTriangle(top, south, west);
            AddTriangle(top, west, north);
            AddTriangle(bottom, east, north);
            AddTriangle(bottom, south, east);
            AddTriangle(bottom, west, south);
            AddTriangle(bottom, north, west);
        }

        public void AddCylinder(Vector3 center, float radius, float height, int segments = 10)
        {
            segments = Mathf.Max(6, segments);
            var bottom = center - Vector3.up * height * 0.5f;
            var top = center + Vector3.up * height * 0.5f;
            for (var index = 0; index < segments; index++)
            {
                var next = (index + 1) % segments;
                var angleA = index * Mathf.PI * 2f / segments;
                var angleB = next * Mathf.PI * 2f / segments;
                var offsetA = new Vector3(Mathf.Cos(angleA) * radius, 0f, Mathf.Sin(angleA) * radius);
                var offsetB = new Vector3(Mathf.Cos(angleB) * radius, 0f, Mathf.Sin(angleB) * radius);
                AddQuad(bottom + offsetA, bottom + offsetB, top + offsetB, top + offsetA,
                    new Vector2(1f / segments, Mathf.Max(1f, height / (radius * 4f))));
                AddTriangle(top, top + offsetA, top + offsetB);
                AddTriangle(bottom, bottom + offsetB, bottom + offsetA);
            }
        }

        public void AddCylinderBetween(Vector3 from, Vector3 to, float radius, int segments = 10)
        {
            segments = Mathf.Max(6, segments);
            var axis = to - from;
            if (axis.sqrMagnitude < 0.0001f || radius <= 0f) return;
            axis.Normalize();
            var tangent = Vector3.Cross(axis, Mathf.Abs(Vector3.Dot(axis, Vector3.up)) > 0.92f ? Vector3.right : Vector3.up).normalized;
            var bitangent = Vector3.Cross(axis, tangent).normalized;
            for (var index = 0; index < segments; index++)
            {
                var next = (index + 1) % segments;
                var angleA = index * Mathf.PI * 2f / segments;
                var angleB = next * Mathf.PI * 2f / segments;
                var ringA = (tangent * Mathf.Cos(angleA) + bitangent * Mathf.Sin(angleA)) * radius;
                var ringB = (tangent * Mathf.Cos(angleB) + bitangent * Mathf.Sin(angleB)) * radius;
                AddQuad(from + ringA, from + ringB, to + ringB, to + ringA,
                    new Vector2(1f / segments, Mathf.Max(1f, Vector3.Distance(from, to) / (radius * 6f))));
                AddTriangle(to, to + ringA, to + ringB);
                AddTriangle(from, from + ringB, from + ringA);
            }
        }

        public void AddEllipsoid(Vector3 center, Vector3 radius, int rings = 6, int segments = 9)
        {
            rings = Mathf.Max(3, rings);
            segments = Mathf.Max(6, segments);
            for (var ring = 0; ring < rings; ring++)
            {
                var latitudeA = -Mathf.PI * 0.5f + ring * Mathf.PI / rings;
                var latitudeB = -Mathf.PI * 0.5f + (ring + 1) * Mathf.PI / rings;
                for (var segment = 0; segment < segments; segment++)
                {
                    var longitudeA = segment * Mathf.PI * 2f / segments;
                    var longitudeB = (segment + 1) * Mathf.PI * 2f / segments;
                    Vector3 Point(float latitude, float longitude) => center + new Vector3(
                        Mathf.Cos(latitude) * Mathf.Cos(longitude) * radius.x,
                        Mathf.Sin(latitude) * radius.y,
                        Mathf.Cos(latitude) * Mathf.Sin(longitude) * radius.z);
                    var a = Point(latitudeA, longitudeA);
                    var b = Point(latitudeA, longitudeB);
                    var c = Point(latitudeB, longitudeB);
                    var d = Point(latitudeB, longitudeA);
                    AddQuad(a, b, c, d, new Vector2(1f / segments, 1f / rings));
                }
            }
        }

        public void AddRibbon(IReadOnlyList<Vector3> points, float width, float height, float textureMeters = 7.5f)
        {
            if (points.Count < 2 || width <= 0f) return;
            for (var index = 0; index < points.Count - 1; index++)
            {
                var from = points[index];
                var to = points[index + 1];
                var direction = to - from;
                direction.y = 0f;
                if (direction.sqrMagnitude < 0.0001f) continue;
                var side = Vector3.Cross(Vector3.up, direction.normalized) * (width * 0.5f);
                from.y = height;
                to.y = height;
                var length = Vector3.Distance(from, to);
                AddQuad(from - side, to - side, to + side, from + side,
                    new Vector2(Mathf.Max(0.1f, length / textureMeters), Mathf.Max(0.1f, width / textureMeters)));
            }
        }

        public void AddExtrudedRibbon(IReadOnlyList<Vector3> points, float width, float baseHeight, float topHeight)
        {
            if (points.Count < 2 || width <= 0f || topHeight <= baseHeight) return;
            for (var index = 0; index < points.Count - 1; index++)
            {
                var from = points[index];
                var to = points[index + 1];
                var direction = to - from;
                direction.y = 0f;
                if (direction.sqrMagnitude < 0.0001f) continue;
                var side = Vector3.Cross(Vector3.up, direction.normalized) * (width * 0.5f);
                var lowerFromLeft = new Vector3(from.x - side.x, baseHeight, from.z - side.z);
                var lowerFromRight = new Vector3(from.x + side.x, baseHeight, from.z + side.z);
                var lowerToLeft = new Vector3(to.x - side.x, baseHeight, to.z - side.z);
                var lowerToRight = new Vector3(to.x + side.x, baseHeight, to.z + side.z);
                var upperFromLeft = new Vector3(lowerFromLeft.x, topHeight, lowerFromLeft.z);
                var upperFromRight = new Vector3(lowerFromRight.x, topHeight, lowerFromRight.z);
                var upperToLeft = new Vector3(lowerToLeft.x, topHeight, lowerToLeft.z);
                var upperToRight = new Vector3(lowerToRight.x, topHeight, lowerToRight.z);
                AddQuad(upperFromLeft, upperToLeft, upperToRight, upperFromRight);
                AddQuad(lowerFromLeft, upperFromLeft, upperToLeft, lowerToLeft);
                AddQuad(lowerToRight, upperToRight, upperFromRight, lowerFromRight);
                AddQuad(lowerFromRight, upperFromRight, upperFromLeft, lowerFromLeft);
                AddQuad(lowerToLeft, upperToLeft, upperToRight, lowerToRight);
            }
        }

        public void AddPolygon(IReadOnlyList<Vector3> source, float height)
        {
            var polygon = Sanitise(source, height);
            if (polygon.Count < 3) return;
            var indices = Triangulate(polygon);
            var start = vertices.Count;
            foreach (var point in polygon)
            {
                vertices.Add(point);
                uv.Add(new Vector2(point.x * 0.05f, point.z * 0.05f));
            }
            // Ear clipping operates in X/Z coordinates, where its positive
            // winding produces a downward Unity normal. Every polygon emitted
            // here is a visible top surface, so flip each triangle upward.
            for (var index = 0; index + 2 < indices.Count; index += 3)
            {
                triangles.Add(start + indices[index]);
                triangles.Add(start + indices[index + 2]);
                triangles.Add(start + indices[index + 1]);
            }
        }

        public void AddExtrudedPolygon(IReadOnlyList<Vector3> source, float baseHeight, float topHeight)
        {
            var polygon = Sanitise(source, baseHeight);
            if (polygon.Count < 3) return;
            AddPolygon(polygon, topHeight);
            for (var index = 0; index < polygon.Count; index++)
            {
                var next = (index + 1) % polygon.Count;
                var a = polygon[index];
                var b = polygon[next];
                var topA = new Vector3(a.x, topHeight, a.z);
                var topB = new Vector3(b.x, topHeight, b.z);
                AddQuad(a, b, topB, topA);
            }
        }

        public void AddFacadeWalls(IReadOnlyList<Vector3> source, float baseHeight, float topHeight, float moduleWidth = 12f)
        {
            var polygon = Sanitise(source, baseHeight);
            if (polygon.Count < 3) return;
            for (var index = 0; index < polygon.Count; index++)
            {
                var next = (index + 1) % polygon.Count;
                var a = polygon[index];
                var b = polygon[next];
                var topA = new Vector3(a.x, topHeight, a.z);
                var topB = new Vector3(b.x, topHeight, b.z);
                AddQuad(a, b, topB, topA, new Vector2(Mathf.Max(1f, Vector3.Distance(a, b) / moduleWidth), 1f));
            }
        }

        public void AddArrow(Vector3 position, Vector3 forward, string direction, float height)
        {
            forward.y = 0f;
            if (forward.sqrMagnitude < 0.001f || string.IsNullOrEmpty(direction)) return;
            forward.Normalize();
            // SUMO Y is mirrored into Unity Z, so preserve SUMO left/right semantics explicitly.
            var side = Vector3.Cross(forward, Vector3.up).normalized;
            Vector3 Ground(Vector3 point) => new(point.x, height, point.z);
            var shaftBack = position - forward * 1.7f;
            var shaftFront = position + forward * 0.55f;
            AddQuad(
                Ground(shaftBack - side * 0.16f), Ground(shaftFront - side * 0.16f),
                Ground(shaftFront + side * 0.16f), Ground(shaftBack + side * 0.16f));

            if (direction.Contains("s"))
            {
                var headBase = position + forward * 0.25f;
                AddTriangle(Ground(headBase - side * 0.64f), Ground(position + forward * 2.2f), Ground(headBase + side * 0.64f));
            }

            void AddTurnHead(Vector3 turn)
            {
                var elbow = position + forward * 0.48f;
                var neck = elbow + turn * 0.78f;
                AddQuad(
                    Ground(elbow - forward * 0.16f), Ground(neck - forward * 0.16f),
                    Ground(neck + forward * 0.16f), Ground(elbow + forward * 0.16f));
                AddTriangle(
                    Ground(neck - forward * 0.62f), Ground(elbow + turn * 1.95f), Ground(neck + forward * 0.62f));
            }

            if (direction.Contains("l")) AddTurnHead(-side);
            if (direction.Contains("r")) AddTurnHead(side);
        }

        public GameObject Build(string name, Material material, Transform parent, bool receiveShadows = true)
        {
            var gameObject = new GameObject(name);
            gameObject.transform.SetParent(parent, false);
            var mesh = new Mesh
            {
                name = $"{name}-mesh",
                indexFormat = vertices.Count > 65535 ? IndexFormat.UInt32 : IndexFormat.UInt16,
            };
            mesh.SetVertices(vertices);
            mesh.SetUVs(0, uv);
            mesh.SetTriangles(triangles, 0, true);
            mesh.RecalculateNormals();
            mesh.RecalculateTangents();
            mesh.RecalculateBounds();
            gameObject.AddComponent<MeshFilter>().sharedMesh = mesh;
            var renderer = gameObject.AddComponent<MeshRenderer>();
            renderer.sharedMaterial = material;
            renderer.shadowCastingMode = receiveShadows ? ShadowCastingMode.On : ShadowCastingMode.Off;
            renderer.receiveShadows = receiveShadows;
            return gameObject;
        }

        private static List<Vector3> Sanitise(IReadOnlyList<Vector3> source, float height)
        {
            var result = new List<Vector3>(source.Count);
            foreach (var raw in source)
            {
                var point = new Vector3(raw.x, height, raw.z);
                if (result.Count == 0 || Vector3.SqrMagnitude(result[^1] - point) > 0.0001f) result.Add(point);
            }
            if (result.Count > 2 && Vector3.SqrMagnitude(result[0] - result[^1]) < 0.0001f) result.RemoveAt(result.Count - 1);
            return result;
        }

        private static List<int> Triangulate(IReadOnlyList<Vector3> polygon)
        {
            var result = new List<int>();
            var available = new List<int>();
            for (var index = 0; index < polygon.Count; index++) available.Add(index);
            if (SignedArea(polygon) < 0f) available.Reverse();

            var guard = polygon.Count * polygon.Count;
            while (available.Count > 2 && guard-- > 0)
            {
                var clipped = false;
                for (var cursor = 0; cursor < available.Count; cursor++)
                {
                    var previous = available[(cursor - 1 + available.Count) % available.Count];
                    var current = available[cursor];
                    var next = available[(cursor + 1) % available.Count];
                    if (!IsConvex(polygon[previous], polygon[current], polygon[next])) continue;
                    var containsPoint = false;
                    foreach (var candidate in available)
                    {
                        if (candidate == previous || candidate == current || candidate == next) continue;
                        if (PointInTriangle(polygon[candidate], polygon[previous], polygon[current], polygon[next]))
                        {
                            containsPoint = true;
                            break;
                        }
                    }
                    if (containsPoint) continue;
                    result.Add(previous);
                    result.Add(current);
                    result.Add(next);
                    available.RemoveAt(cursor);
                    clipped = true;
                    break;
                }
                if (!clipped) break;
            }
            return result;
        }

        private static float SignedArea(IReadOnlyList<Vector3> polygon)
        {
            var area = 0f;
            for (var index = 0; index < polygon.Count; index++)
            {
                var next = (index + 1) % polygon.Count;
                area += polygon[index].x * polygon[next].z - polygon[next].x * polygon[index].z;
            }
            return area * 0.5f;
        }

        private static bool IsConvex(Vector3 a, Vector3 b, Vector3 c)
        {
            return ((b.x - a.x) * (c.z - b.z) - (b.z - a.z) * (c.x - b.x)) > 0.00001f;
        }

        private static bool PointInTriangle(Vector3 point, Vector3 a, Vector3 b, Vector3 c)
        {
            static float Sign(Vector3 p1, Vector3 p2, Vector3 p3) =>
                (p1.x - p3.x) * (p2.z - p3.z) - (p2.x - p3.x) * (p1.z - p3.z);
            var d1 = Sign(point, a, b);
            var d2 = Sign(point, b, c);
            var d3 = Sign(point, c, a);
            var hasNegative = d1 < 0f || d2 < 0f || d3 < 0f;
            var hasPositive = d1 > 0f || d2 > 0f || d3 > 0f;
            return !(hasNegative && hasPositive);
        }
    }
}
