using UnityEngine;
using Xiongan.DigitalTwin.Data;

namespace Xiongan.DigitalTwin.Core
{
    public sealed class CoordinateService
    {
        public Point2 Origin { get; }

        public CoordinateService(Point2 origin)
        {
            Origin = origin;
        }

        public Vector3 ToWorld(float sumoX, float sumoY, float height = 0f)
        {
            return new Vector3(sumoX - Origin.X, height, Origin.Y - sumoY);
        }

        public Vector3 ToWorld(Point2 point, float height = 0f)
        {
            return ToWorld(point.X, point.Y, height);
        }

        public Quaternion ToWorldRotation(float sumoAngle)
        {
            return Quaternion.Euler(0f, -sumoAngle, 0f);
        }
    }
}
