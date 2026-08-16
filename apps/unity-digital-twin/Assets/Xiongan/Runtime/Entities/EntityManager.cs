using System;
using System.Collections.Generic;
using UnityEngine;
using Xiongan.DigitalTwin.Core;
using Xiongan.DigitalTwin.Data;

namespace Xiongan.DigitalTwin.Entities
{
    public sealed class EntityManager : MonoBehaviour
    {
        private readonly Dictionary<string, EntityActor> vehicles = new();
        private readonly Dictionary<string, EntityActor> bicycles = new();
        private readonly Dictionary<string, EntityActor> pedestrians = new();
        private readonly Stack<EntityActor> vehiclePool = new();
        private readonly Stack<EntityActor> bicyclePool = new();
        private readonly Stack<EntityActor> pedestrianPool = new();
        private CoordinateService coordinates = null!;
        private MaterialLibrary materials = null!;
        private float tickHz = 1f;

        public int VehicleCount => vehicles.Count;
        public int BicycleCount => bicycles.Count;
        public int PedestrianCount => pedestrians.Count;

        public void Initialise(CoordinateService coordinateService, MaterialLibrary materialLibrary)
        {
            coordinates = coordinateService;
            materials = materialLibrary;
        }

        public void ApplyInit(DigitalTwinInit message)
        {
            ClearAll();
            tickHz = message.TickHz;
            foreach (var item in message.Entities.Vehicles) SpawnVehicle(item, "vehicle", true);
            foreach (var item in message.Entities.Bicycles) SpawnVehicle(item, "bicycle", true);
            foreach (var item in message.Entities.Pedestrians) SpawnPedestrian(item, true);
        }

        public void ApplyDelta(DigitalTwinDelta message)
        {
            foreach (var id in message.Remove.Vehicles) Recycle(vehicles, vehiclePool, id);
            foreach (var id in message.Remove.Bicycles) Recycle(bicycles, bicyclePool, id);
            foreach (var id in message.Remove.Pedestrians) Recycle(pedestrians, pedestrianPool, id);
            foreach (var item in message.Spawn.Vehicles) SpawnVehicle(item, "vehicle", true);
            foreach (var item in message.Spawn.Bicycles) SpawnVehicle(item, "bicycle", true);
            foreach (var item in message.Spawn.Pedestrians) SpawnPedestrian(item, true);
            foreach (var item in message.Update.Vehicles) UpdateVehicle(item, vehicles);
            foreach (var item in message.Update.Bicycles) UpdateVehicle(item, bicycles);
            foreach (var item in message.Update.Pedestrians) UpdatePedestrian(item);
        }

        public void ApplySnapshot(BrowserSnapshot snapshot)
        {
            tickHz = snapshot.TickHz;
            SyncSnapshot(snapshot.Entities.Vehicles, vehicles, vehiclePool, "vehicle");
            SyncSnapshot(snapshot.Entities.Bicycles, bicycles, bicyclePool, "bicycle");
            var pedestrianIds = new HashSet<string>();
            foreach (var item in snapshot.Entities.Pedestrians)
            {
                pedestrianIds.Add(item.Id);
                if (!pedestrians.ContainsKey(item.Id)) SpawnPedestrian(item, true);
                else UpdatePedestrian(item);
            }
            foreach (var id in new List<string>(pedestrians.Keys)) if (!pedestrianIds.Contains(id)) Recycle(pedestrians, pedestrianPool, id);
        }

        public EntityActor? Find(string identifier)
        {
            if (vehicles.TryGetValue(identifier, out var vehicle)) return vehicle;
            if (bicycles.TryGetValue(identifier, out var bicycle)) return bicycle;
            return pedestrians.TryGetValue(identifier, out var pedestrian) ? pedestrian : null;
        }

        public bool TryGetVehicleClusterCenter(out Vector3 center)
        {
            center = Vector3.zero;
            if (vehicles.Count == 0) return false;
            const float clusterRadius = 78f;
            var radiusSquared = clusterRadius * clusterRadius;
            var bestCount = 0;
            foreach (var candidate in vehicles.Values)
            {
                var sum = Vector3.zero;
                var count = 0;
                foreach (var actor in vehicles.Values)
                {
                    var delta = actor.transform.position - candidate.transform.position;
                    delta.y = 0f;
                    if (delta.sqrMagnitude > radiusSquared) continue;
                    sum += actor.transform.position;
                    count++;
                }
                if (count <= bestCount) continue;
                bestCount = count;
                center = sum / count;
            }
            return bestCount > 0;
        }

        private void SyncSnapshot(IEnumerable<VehicleEntity> source, Dictionary<string, EntityActor> target, Stack<EntityActor> pool, string category)
        {
            var ids = new HashSet<string>();
            foreach (var item in source)
            {
                ids.Add(item.Id);
                if (!target.ContainsKey(item.Id)) SpawnVehicle(item, category, true);
                else UpdateVehicle(item, target);
            }
            foreach (var id in new List<string>(target.Keys)) if (!ids.Contains(id)) Recycle(target, pool, id);
        }

        private void SpawnVehicle(VehicleEntity item, string category, bool immediate)
        {
            var target = category == "bicycle" ? bicycles : vehicles;
            var pool = category == "bicycle" ? bicyclePool : vehiclePool;
            if (target.TryGetValue(item.Id, out var existing))
            {
                existing.SetTarget(item.X, item.Y, item.Angle, item.Speed, tickHz, coordinates, immediate);
                existing.SetBrake(item.Brake);
                return;
            }
            var actor = pool.Count > 0 ? pool.Pop() : CreateActor(item.Id, category, ResolveColor(item), materials);
            actor.Rebind(item.Id);
            actor.gameObject.SetActive(true);
            actor.SetTarget(item.X, item.Y, item.Angle, item.Speed, tickHz, coordinates, immediate);
            actor.SetBrake(item.Brake);
            target[item.Id] = actor;
        }

        private void SpawnPedestrian(PedestrianEntity item, bool immediate)
        {
            if (pedestrians.TryGetValue(item.Id, out var existing))
            {
                existing.SetTarget(item.X, item.Y, item.Angle, item.Speed, tickHz, coordinates, immediate);
                return;
            }
            var actor = pedestrianPool.Count > 0 ? pedestrianPool.Pop() : CreateActor(item.Id, "pedestrian", DeterministicColor(item.Id), materials);
            actor.Rebind(item.Id);
            actor.gameObject.SetActive(true);
            actor.SetTarget(item.X, item.Y, item.Angle, item.Speed, tickHz, coordinates, immediate);
            pedestrians[item.Id] = actor;
        }

        private void UpdateVehicle(VehicleEntity item, Dictionary<string, EntityActor> target)
        {
            if (!target.TryGetValue(item.Id, out var actor))
            {
                SpawnVehicle(item, ReferenceEquals(target, bicycles) ? "bicycle" : "vehicle", true);
                return;
            }
            actor.SetTarget(item.X, item.Y, item.Angle, item.Speed, tickHz, coordinates);
            actor.SetBrake(item.Brake);
        }

        private void UpdatePedestrian(PedestrianEntity item)
        {
            if (!pedestrians.TryGetValue(item.Id, out var actor))
            {
                SpawnPedestrian(item, true);
                return;
            }
            actor.SetTarget(item.X, item.Y, item.Angle, item.Speed, tickHz, coordinates);
        }

        private EntityActor CreateActor(string id, string category, Color color, MaterialLibrary library)
        {
            var actor = new GameObject().AddComponent<EntityActor>();
            actor.transform.SetParent(transform, false);
            actor.Initialise(id, category, library, color);
            return actor;
        }

        private static Color ResolveColor(VehicleEntity entity)
        {
            if (!ColorUtility.TryParseHtmlString(entity.Color, out var parsed)) return DeterministicColor(entity.Id);
            // The organiser replay uses bright yellow as a connected-vehicle
            // category code. Preserve that semantic in data, but do not render
            // every vehicle as though it had identical yellow body paint.
            Color.RGBToHSV(parsed, out var hue, out var saturation, out var value);
            var categoryYellow = hue >= 0.105f && hue <= 0.19f && saturation > 0.72f && value > 0.82f;
            return categoryYellow ? DeterministicColor(entity.Id) : parsed;
        }

        private static Color DeterministicColor(string id)
        {
            var palette = new[]
            {
                new Color(0.92f, 0.94f, 0.95f), new Color(0.075f, 0.09f, 0.105f),
                new Color(0.68f, 0.7f, 0.72f), new Color(0.10f, 0.30f, 0.56f),
                new Color(0.62f, 0.055f, 0.045f), new Color(0.22f, 0.34f, 0.31f),
                new Color(0.82f, 0.82f, 0.78f), new Color(0.28f, 0.20f, 0.16f),
            };
            unchecked
            {
                var hash = 17;
                foreach (var character in id) hash = hash * 31 + character;
                return palette[Mathf.Abs(hash) % palette.Length];
            }
        }

        private static void Recycle(Dictionary<string, EntityActor> source, Stack<EntityActor> pool, string id)
        {
            if (!source.Remove(id, out var actor)) return;
            actor.gameObject.SetActive(false);
            pool.Push(actor);
        }

        private void ClearAll()
        {
            foreach (var id in new List<string>(vehicles.Keys)) Recycle(vehicles, vehiclePool, id);
            foreach (var id in new List<string>(bicycles.Keys)) Recycle(bicycles, bicyclePool, id);
            foreach (var id in new List<string>(pedestrians.Keys)) Recycle(pedestrians, pedestrianPool, id);
        }
    }
}
