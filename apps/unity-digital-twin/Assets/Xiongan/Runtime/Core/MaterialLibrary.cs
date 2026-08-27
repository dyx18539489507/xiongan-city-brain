using System.Collections.Generic;
using UnityEngine;

namespace Xiongan.DigitalTwin.Core
{
    public sealed class MaterialLibrary
    {
        private readonly List<Material> owned = new();
        private readonly List<Material> facadeMaterials = new();

        public Material Asphalt { get; }
        public Material HeroAsphalt { get; }
        public Material Junction { get; }
        public Material Marking { get; }
        public Material MarkingYellow { get; }
        public Material Bicycle { get; }
        public Material Sidewalk { get; }
        public Material HeroSidewalk { get; }
        public Material ParkingGround { get; }
        public Material ConstructionGround { get; }
        public Material UrbanGround { get; }
        public Material HeroGrass { get; }
        public Material Grass { get; }
        public Material Building { get; }
        public Material BuildingGlass { get; }
        public Material BuildingGlassWarm { get; }
        public Material FacadeFrame { get; }
        public Material BuildingRoof { get; }
        public Material ArchitecturalStone { get; }
        public Material CivicCladding { get; }
        public Material BrickAccent { get; }
        public Material GreyRoofTile { get; }
        public Material TimberScreen { get; }
        public Material Curb { get; }
        public Material TreeBark { get; }
        public Material TreeLeaves { get; }
        public Material ShrubLeaves { get; }
        public Material FormalTreeLeaves { get; }
        public Material FormalTreeBranches { get; }
        public Material PbrTreeLeaves { get; }
        public Material PbrTreeBranches { get; }
        public Material PbrStreetLamp { get; }
        public Material Metal { get; }
        public Material Chrome { get; }
        public Material Rubber { get; }
        public Material SignalDark { get; }
        public Material SignalRed { get; }
        public Material SignalYellow { get; }
        public Material SignalGreen { get; }
        public Material WayfindingBlue { get; }
        public Material Headlight { get; }
        public Material Alert { get; }
        public IReadOnlyList<Material> Facades => facadeMaterials;

        public MaterialLibrary()
        {
            // Surfaces are deliberately texture-free.  Their apparent material
            // comes from physical mesh detail, vertex geometry, lighting and the
            // URP BRDF rather than an albedo/normal photograph.
            Asphalt = CreateProcedural(new Color(0.132f, 0.142f, 0.151f), new Color(0.072f, 0.078f, 0.084f), 15.5f, 0.24f, 0.2f, 0f, 0f);
            HeroAsphalt = CreateProcedural(new Color(0.145f, 0.154f, 0.162f), new Color(0.078f, 0.084f, 0.091f), 17.2f, 0.25f, 0.22f, 0f, 0f);
            Junction = CreateProcedural(new Color(0.138f, 0.148f, 0.156f), new Color(0.075f, 0.081f, 0.087f), 15.8f, 0.23f, 0.2f, 0f, 0f);
            Sidewalk = CreateProcedural(new Color(0.52f, 0.505f, 0.47f), new Color(0.37f, 0.36f, 0.335f), 2.35f, 0.11f, 0.06f, 0f, 1f);
            HeroSidewalk = CreateProcedural(new Color(0.56f, 0.545f, 0.505f), new Color(0.405f, 0.39f, 0.36f), 2.55f, 0.11f, 0.07f, 0f, 1f);
            ParkingGround = CreateProcedural(new Color(0.37f, 0.365f, 0.345f), new Color(0.275f, 0.27f, 0.255f), 3.2f, 0.09f, 0.1f, 0f, 1f);
            ConstructionGround = CreateProcedural(new Color(0.355f, 0.325f, 0.27f), new Color(0.245f, 0.225f, 0.19f), 4.7f, 0.13f, 0.04f, 0f, 0f);
            UrbanGround = CreateProcedural(new Color(0.205f, 0.282f, 0.142f), new Color(0.108f, 0.16f, 0.074f), 4.2f, 0.1f, 0.035f, 0f, 0f);
            HeroGrass = CreateProcedural(new Color(0.235f, 0.335f, 0.16f), new Color(0.125f, 0.19f, 0.078f), 5.2f, 0.11f, 0.035f, 0f, 0f);
            Grass = CreateProcedural(new Color(0.205f, 0.305f, 0.14f), new Color(0.108f, 0.172f, 0.068f), 4.8f, 0.1f, 0.035f, 0f, 0f);
            Marking = Create(new Color(0.97f, 0.98f, 0.955f), 0.3f, 0f);
            // Xiong'an's showcase corridor uses a restrained warm edge line;
            // the previous saturated orange read like a game debug overlay.
            MarkingYellow = Create(new Color(0.82f, 0.78f, 0.57f), 0.28f, 0f);
            Bicycle = Create(new Color(0.085f, 0.038f, 0.026f), 0.18f, 0f);
            Building = Create(new Color(0.68f, 0.69f, 0.67f), 0.24f, 0.01f);
            // Opaque high-gloss architectural glass remains legible in WebGL
            // without reflecting a photographed environment or revealing the
            // empty interior of a procedural building.
            BuildingGlass = CreateProcedural(new Color(0.32f, 0.49f, 0.61f), new Color(0.125f, 0.275f, 0.365f), 0.16f, 0.16f, 0.94f, 0.16f, 3f);
            BuildingGlassWarm = CreateProcedural(new Color(0.55f, 0.43f, 0.29f), new Color(0.255f, 0.195f, 0.125f), 0.16f, 0.15f, 0.9f, 0.1f, 3f);
            FacadeFrame = Create(new Color(0.265f, 0.285f, 0.295f), 0.48f, 0.34f);
            BuildingRoof = CreateProcedural(new Color(0.39f, 0.42f, 0.415f), new Color(0.24f, 0.265f, 0.26f), 2.15f, 0.13f, 0.18f, 0f, 1f);
            ArchitecturalStone = CreateProcedural(new Color(0.56f, 0.555f, 0.52f), new Color(0.37f, 0.37f, 0.345f), 3.6f, 0.12f, 0.2f, 0f, 2f);
            CivicCladding = Create(new Color(0.94f, 0.945f, 0.925f), 0.22f, 0f);
            BrickAccent = CreateProcedural(new Color(0.42f, 0.18f, 0.135f), new Color(0.245f, 0.08f, 0.058f), 5.8f, 0.14f, 0.18f, 0f, 2f);
            GreyRoofTile = CreateProcedural(new Color(0.23f, 0.255f, 0.255f), new Color(0.125f, 0.145f, 0.148f), 7.2f, 0.13f, 0.25f, 0f, 1f);
            TimberScreen = CreateProcedural(new Color(0.285f, 0.17f, 0.105f), new Color(0.145f, 0.075f, 0.042f), 4.4f, 0.12f, 0.28f, 0f, 2f);
            Curb = CreateProcedural(new Color(0.755f, 0.76f, 0.735f), new Color(0.57f, 0.575f, 0.55f), 3.1f, 0.09f, 0.24f, 0f, 1f);
            TreeBark = Create(new Color(0.24f, 0.145f, 0.072f), 0.08f, 0f);
            TreeLeaves = CreateProcedural(new Color(0.12f, 0.31f, 0.075f), new Color(0.045f, 0.145f, 0.035f), 5.4f, 0.22f, 0.07f, 0f, 0f);
            ShrubLeaves = CreateProcedural(new Color(0.14f, 0.31f, 0.07f), new Color(0.05f, 0.15f, 0.03f), 6.1f, 0.24f, 0.08f, 0f, 0f);
            FormalTreeLeaves = CreateProcedural(new Color(0.16f, 0.36f, 0.09f), new Color(0.06f, 0.18f, 0.035f), 5.7f, 0.22f, 0.06f, 0f, 0f);
            FormalTreeBranches = Create(new Color(0.215f, 0.125f, 0.064f), 0.12f, 0f);
            // These maps are used only by their corresponding three-dimensional
            // CC0 prop meshes. Road asphalt, walls, facades and terrain remain
            // entirely texture-free and are guarded by the editor build gate.
            PbrTreeLeaves = CreateTextured(
                "Art/Models/island_tree_02/Textures/island_tree_02_leaves_diff_1k",
                "Art/Models/island_tree_02/Textures/island_tree_02_leaves_nor_gl_1k",
                new Color(0.38f, 0.56f, 0.32f), 0.12f, 0f, true);
            PbrTreeBranches = CreateTextured(
                "Art/Models/island_tree_02/Textures/island_tree_02_branches_diff_1k",
                "Art/Models/island_tree_02/Textures/island_tree_02_branches_nor_gl_1k",
                new Color(0.7f, 0.64f, 0.54f), 0.18f, 0f, false);
            PbrStreetLamp = CreateTextured(
                "Art/Models/street_lamp_01/Textures/street_lamp_01_diff_1k",
                null,
                Color.white, 0.56f, 0.72f, false);
            Metal = Create(new Color(0.205f, 0.235f, 0.255f), 0.62f, 0.78f);
            Chrome = Create(new Color(0.6f, 0.64f, 0.66f), 0.9f, 0.96f);
            Rubber = Create(new Color(0.026f, 0.03f, 0.034f), 0.14f, 0f);
            SignalDark = Create(new Color(0.018f, 0.025f, 0.026f), 0.34f, 0.12f);
            SignalRed = Create(new Color(0.82f, 0.008f, 0.003f), 0.54f, 0.05f);
            SignalYellow = Create(new Color(0.92f, 0.31f, 0.006f), 0.52f, 0.04f);
            SignalGreen = Create(new Color(0.006f, 0.66f, 0.045f), 0.52f, 0.04f);
            WayfindingBlue = Create(new Color(0.035f, 0.24f, 0.48f), 0.42f, 0.18f);
            Headlight = CreateEmission(new Color(0.82f, 0.92f, 1f), 1.8f);
            Alert = CreateEmission(new Color(1f, 0.16f, 0.025f), 3.2f);

            foreach (var color in new[]
                     {
                         new Color(0.74f, 0.75f, 0.72f), new Color(0.68f, 0.71f, 0.72f),
                         new Color(0.78f, 0.75f, 0.68f), new Color(0.72f, 0.74f, 0.73f),
                         new Color(0.71f, 0.71f, 0.67f), new Color(0.79f, 0.78f, 0.73f),
                         new Color(0.65f, 0.72f, 0.73f), new Color(0.73f, 0.74f, 0.7f),
                     }) facadeMaterials.Add(CreateProcedural(color, color * 0.8f, 5.8f, 0.14f, 0.19f, 0.006f, 2f));
        }

        public Material Create(Color color, float smoothness, float metallic)
        {
            var material = NewLit();
            SetColor(material, color);
            SetFloat(material, "_Smoothness", "_Glossiness", smoothness);
            if (material.HasProperty("_Metallic")) material.SetFloat("_Metallic", metallic);
            return material;
        }

        private Material CreateProcedural(
            Color primary, Color secondary, float scale, float strength,
            float smoothness, float metallic, float mode)
        {
            var shader = Shader.Find("Xiongan/ProceduralSurface");
            if (shader == null) return Create(primary, smoothness, metallic);
            var material = new Material(shader) { enableInstancing = true };
            material.SetColor("_BaseColor", primary);
            material.SetColor("_SecondaryColor", secondary);
            material.SetFloat("_DetailScale", scale);
            material.SetFloat("_DetailStrength", strength);
            material.SetFloat("_Smoothness", smoothness);
            material.SetFloat("_Metallic", metallic);
            material.SetFloat("_Mode", mode);
            owned.Add(material);
            return material;
        }

        private Material CreateTextured(
            string baseMapPath, string normalMapPath, Color tint,
            float smoothness, float metallic, bool alphaClipped)
        {
            var material = NewLit();
            var baseMap = Resources.Load<Texture2D>(baseMapPath);
            if (baseMap != null)
            {
                if (material.HasProperty("_BaseMap")) material.SetTexture("_BaseMap", baseMap);
                if (material.HasProperty("_MainTex")) material.SetTexture("_MainTex", baseMap);
            }
            SetColor(material, tint);
            SetFloat(material, "_Smoothness", "_Glossiness", smoothness);
            if (material.HasProperty("_Metallic")) material.SetFloat("_Metallic", metallic);

            var normalMap = string.IsNullOrEmpty(normalMapPath) ? null : Resources.Load<Texture2D>(normalMapPath);
            if (normalMap != null && material.HasProperty("_BumpMap"))
            {
                material.SetTexture("_BumpMap", normalMap);
                if (material.HasProperty("_BumpScale")) material.SetFloat("_BumpScale", 0.72f);
                material.EnableKeyword("_NORMALMAP");
            }

            if (alphaClipped)
            {
                if (material.HasProperty("_AlphaClip")) material.SetFloat("_AlphaClip", 1f);
                if (material.HasProperty("_Cutoff")) material.SetFloat("_Cutoff", 0.2f);
                if (material.HasProperty("_Cull")) material.SetFloat("_Cull", 0f);
                material.EnableKeyword("_ALPHATEST_ON");
                material.SetOverrideTag("RenderType", "TransparentCutout");
                material.renderQueue = 2450;
                material.doubleSidedGI = true;
            }
            return material;
        }

        private Material CreateTransparent(Color color, float smoothness, float metallic)
        {
            var material = Create(color, smoothness, metallic);
            if (material.HasProperty("_Surface")) material.SetFloat("_Surface", 1f);
            if (material.HasProperty("_Blend")) material.SetFloat("_Blend", 0f);
            material.SetOverrideTag("RenderType", "Transparent");
            material.renderQueue = 3000;
            material.EnableKeyword("_SURFACE_TYPE_TRANSPARENT");
            material.EnableKeyword("_ALPHAPREMULTIPLY_ON");
            return material;
        }

        private Material CreateEmission(Color color, float intensity)
        {
            var material = Create(color * 0.12f, 0.62f, 0.08f);
            material.EnableKeyword("_EMISSION");
            if (material.HasProperty("_EmissionColor")) material.SetColor("_EmissionColor", color * intensity);
            return material;
        }

        private Material NewLit()
        {
            var shader = Shader.Find("Universal Render Pipeline/Lit") ?? Shader.Find("Standard");
            var material = new Material(shader) { enableInstancing = true };
            owned.Add(material);
            return material;
        }

        private static void SetColor(Material material, Color color)
        {
            if (material.HasProperty("_BaseColor")) material.SetColor("_BaseColor", color);
            if (material.HasProperty("_Color")) material.SetColor("_Color", color);
        }

        private static void SetFloat(Material material, string primary, string fallback, float value)
        {
            if (material.HasProperty(primary)) material.SetFloat(primary, value);
            else if (material.HasProperty(fallback)) material.SetFloat(fallback, value);
        }

        public void Dispose()
        {
            foreach (var material in owned) if (material != null) Object.Destroy(material);
            owned.Clear();
            facadeMaterials.Clear();
        }

        public void ReleaseOwnership() => owned.Clear();
    }
}
