Shader "Xiongan/ProceduralSurface"
{
    Properties
    {
        _BaseColor("Base color", Color) = (0.2,0.2,0.2,1)
        _SecondaryColor("Secondary color", Color) = (0.12,0.12,0.12,1)
        _DetailScale("Detail scale", Float) = 7
        _DetailStrength("Detail strength", Range(0,1)) = 0.2
        _Smoothness("Smoothness", Range(0,1)) = 0.2
        _Metallic("Metallic", Range(0,1)) = 0
        _Mode("Surface mode", Float) = 0
    }
    SubShader
    {
        Tags { "RenderType"="Opaque" "RenderPipeline"="UniversalPipeline" "Queue"="Geometry" }
        LOD 300

        Pass
        {
            Name "UniversalForward"
            Tags { "LightMode"="UniversalForward" }
            HLSLPROGRAM
            #pragma target 3.0
            #pragma vertex Vert
            #pragma fragment Frag
            #pragma multi_compile _ _MAIN_LIGHT_SHADOWS _MAIN_LIGHT_SHADOWS_CASCADE
            #pragma multi_compile_fragment _ _SHADOWS_SOFT
            #pragma multi_compile_fragment _ _SCREEN_SPACE_OCCLUSION
            #pragma multi_compile _ _ADDITIONAL_LIGHTS_VERTEX _ADDITIONAL_LIGHTS
            #pragma multi_compile_fog
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Lighting.hlsl"

            CBUFFER_START(UnityPerMaterial)
                float4 _BaseColor;
                float4 _SecondaryColor;
                float _DetailScale;
                float _DetailStrength;
                float _Smoothness;
                float _Metallic;
                float _Mode;
            CBUFFER_END

            struct Attributes
            {
                float4 positionOS : POSITION;
                float3 normalOS : NORMAL;
            };

            struct Varyings
            {
                float4 positionCS : SV_POSITION;
                float3 positionWS : TEXCOORD0;
                half3 normalWS : TEXCOORD1;
                half fogFactor : TEXCOORD2;
                float4 shadowCoord : TEXCOORD3;
            };

            float Hash21(float2 p)
            {
                p = frac(p * float2(123.34, 456.21));
                p += dot(p, p + 45.32);
                return frac(p.x * p.y);
            }

            float ValueNoise(float2 p)
            {
                float2 i = floor(p);
                float2 f = frac(p);
                f = f * f * (3.0 - 2.0 * f);
                return lerp(lerp(Hash21(i), Hash21(i + float2(1, 0)), f.x),
                            lerp(Hash21(i + float2(0, 1)), Hash21(i + 1), f.x), f.y);
            }

            float DetailNoise(float2 p)
            {
                // Broad variation and sub-pixel grain are composed separately
                // below, so a second octave here only repeats fragment work.
                return ValueNoise(p);
            }

            float2 SurfacePlane(float3 positionWS, half3 normalWS)
            {
                if (_Mode < 1.5 || abs(normalWS.y) > 0.72h) return positionWS.xz;
                return abs(normalWS.x) > abs(normalWS.z) ? positionWS.zy : positionWS.xy;
            }

            Varyings Vert(Attributes input)
            {
                Varyings output;
                VertexPositionInputs positionInputs = GetVertexPositionInputs(input.positionOS.xyz);
                output.positionCS = positionInputs.positionCS;
                output.positionWS = positionInputs.positionWS;
                output.normalWS = TransformObjectToWorldNormal(input.normalOS);
                output.fogFactor = ComputeFogFactor(positionInputs.positionCS.z);
                output.shadowCoord = TransformWorldToShadowCoord(positionInputs.positionWS);
                return output;
            }

            half4 Frag(Varyings input) : SV_Target
            {
                half3 normalWS = normalize(input.normalWS);
                float2 plane = SurfacePlane(input.positionWS, normalWS);
                // World-space procedural detail must disappear before its
                // frequency becomes smaller than a screen pixel. Without this
                // footprint filter, roofs and paving form unstable moire bands
                // in district and overview cameras.
                float worldUnitsPerPixel = max(length(ddx(plane)), length(ddy(plane)));
                float detailPixels = worldUnitsPerPixel * _DetailScale;
                float fineVisibility = 1.0 - smoothstep(0.08, 0.34, detailPixels);
                float broadVisibility = 1.0 - smoothstep(0.12, 0.52, detailPixels * 0.115);
                float fine = lerp(0.5, DetailNoise(plane * _DetailScale), fineVisibility);
                float broad = lerp(0.5, ValueNoise(plane * (_DetailScale * 0.115) + 17.7), broadVisibility);
                // Discontinuous hash grain cannot be analytically minified and
                // scintillates as the camera moves. Continuous band-limited
                // fields retain material variation without one-frame sparkles.
                float aggregate = saturate(fine * 0.72 + broad * 0.28);
                float blend = saturate(0.5 + (aggregate - 0.5) * (0.72 + _DetailStrength * 1.65));
                half3 albedo = lerp(_SecondaryColor.rgb, _BaseColor.rgb, blend);

                // Paving joints and cast-concrete seams are generated in the
                // shader. The material never samples an asphalt or wall image.
                if (_Mode > 0.5 && _Mode < 1.5)
                {
                    float2 tile = abs(frac(plane * 0.46) - 0.5);
                    float tileEdge = max(tile.x, tile.y);
                    float tileAA = max(fwidth(tileEdge), 0.0005);
                    float joint = smoothstep(0.472 - tileAA, 0.497 + tileAA, tileEdge);
                    float stagger = step(0.5, frac(floor(plane.y * 0.46) * 0.5));
                    float verticalEdge = abs(frac(plane.x * 0.46 + stagger * 0.5) - 0.5);
                    float verticalAA = max(fwidth(verticalEdge), 0.0005);
                    float verticalJoint = smoothstep(0.478 - verticalAA, 0.498 + verticalAA, verticalEdge);
                    float jointVisibility = 1.0 - smoothstep(0.1, 0.4, worldUnitsPerPixel * 0.46);
                    albedo *= lerp(1.0h, 0.72h,
                        max(joint * 0.45, verticalJoint * 0.5) * jointVisibility);
                }
                else if (_Mode > 1.5 && _Mode < 2.5)
                {
                    float floorCoordinate = abs(frac(input.positionWS.y / 3.35) - 0.5);
                    float floorAA = max(fwidth(floorCoordinate), 0.0005);
                    float floorJoint = smoothstep(0.485 - floorAA, 0.5, floorCoordinate);
                    float formworkCoordinate = abs(frac(plane.x * 0.28) - 0.5);
                    float formworkAA = max(fwidth(formworkCoordinate), 0.0005);
                    float formwork = smoothstep(0.493 - formworkAA, 0.5, formworkCoordinate);
                    float seamPixels = max(fwidth(input.positionWS.y / 3.35), fwidth(plane.x * 0.28));
                    float seamVisibility = 1.0 - smoothstep(0.1, 0.4, seamPixels);
                    albedo *= lerp(1.0h, 0.88h,
                        (floorJoint * 0.36 + formwork * 0.08) * seamVisibility);

                    // Texture-free mineral surfaces need large-scale tonal
                    // variation as well as seams. This low-frequency field and
                    // restrained ground contact darkening prevent a facade from
                    // reading as a perfectly uniform white game block.
                    float facadeMottle = ValueNoise(float2(
                        plane.x * 0.075 + 9.7,
                        input.positionWS.y * 0.045 + 31.2));
                    float facadeMottleVisibility = 1.0 - smoothstep(
                        0.25, 1.1, worldUnitsPerPixel * 0.075);
                    albedo *= lerp(1.0h,
                        lerp(0.93h, 1.035h, facadeMottle),
                        facadeMottleVisibility * 0.72);
                    float contactPatina = exp2(-max(input.positionWS.y, 0.0) * 0.42);
                    albedo *= lerp(1.0h, 0.91h, contactPatina * 0.55h);
                }
                else if (_Mode > 2.5)
                {
                    // Texture-free glazing uses the viewing angle, sky-facing
                    // normal and a broad world-space field to break the flat
                    // black-window look while preserving opaque WebGL geometry.
                    half3 viewDirection = GetWorldSpaceNormalizeViewDir(input.positionWS);
                    half grazing = pow(1.0h - saturate(dot(normalWS, viewDirection)), 3.0h);
                    half skyFacing = saturate(normalWS.y * 0.45h + 0.55h);
                    float reflectionField = ValueNoise(
                        plane * 0.085 + input.positionWS.y / 3.35 * float2(0.37, 0.61));
                    half reflection = saturate(grazing * 0.58h + skyFacing * 0.16h +
                        reflectionField * 0.26h);
                    albedo *= lerp(0.82h, 1.2h, reflection);
                    albedo = lerp(albedo, half3(0.33h, 0.48h, 0.58h), grazing * 0.24h);
                }

                if (_Mode < 1.5 && abs(normalWS.y) > 0.72h)
                {
                    // Reuse the already-computed noise derivative instead of
                    // evaluating the full noise field two more times per pixel.
                    // Projecting the screen derivatives back onto the surface
                    // keeps the same fine highlight breakup at a fraction of
                    // the fragment cost.
                    float3 positionDx = ddx(input.positionWS);
                    float3 positionDy = ddy(input.positionWS);
                    float3 surfaceGradient =
                        positionDx * (ddx(fine) / max(dot(positionDx, positionDx), 0.0001)) +
                        positionDy * (ddy(fine) / max(dot(positionDy, positionDy), 0.0001));
                    surfaceGradient -= normalWS * dot(surfaceGradient, normalWS);
                    normalWS = normalize(normalWS - surfaceGradient *
                        (_DetailStrength * 0.62 * fineVisibility));
                }

                InputData inputData = (InputData)0;
                inputData.positionWS = input.positionWS;
                inputData.positionCS = input.positionCS;
                inputData.normalWS = normalWS;
                inputData.viewDirectionWS = GetWorldSpaceNormalizeViewDir(input.positionWS);
                inputData.shadowCoord = input.shadowCoord;
                inputData.fogCoord = input.fogFactor;
                inputData.vertexLighting = half3(0, 0, 0);
                inputData.bakedGI = SampleSH(normalWS);
                inputData.normalizedScreenSpaceUV = GetNormalizedScreenSpaceUV(input.positionCS);
                inputData.shadowMask = half4(1, 1, 1, 1);

                half occlusion = lerp(1.0h, 0.88h, _DetailStrength * saturate(0.58h - aggregate));
                half surfaceSmoothness = saturate(_Smoothness +
                    (aggregate - 0.5h) * (_Mode > 2.5 ? 0.08h : 0.035h));
                half4 color = UniversalFragmentPBR(
                    inputData, albedo, _Metallic, half3(0, 0, 0),
                    surfaceSmoothness, occlusion, half3(0, 0, 0), 1.0h);
                color.rgb = MixFog(color.rgb, input.fogFactor);
                return color;
            }
            ENDHLSL
        }

        UsePass "Universal Render Pipeline/Lit/ShadowCaster"
        UsePass "Universal Render Pipeline/Lit/DepthOnly"
        UsePass "Universal Render Pipeline/Lit/DepthNormals"
    }
}
