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

            float Fbm(float2 p)
            {
                float value = ValueNoise(p) * 0.58;
                value += ValueNoise(p * 2.07 + 19.7) * 0.28;
                value += ValueNoise(p * 4.13 - 8.4) * 0.14;
                return value;
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
                float fine = Fbm(plane * _DetailScale);
                float broad = Fbm(plane * (_DetailScale * 0.115) + 17.7);
                float grain = Hash21(floor(plane * _DetailScale * 7.0));
                float aggregate = saturate(fine * 0.66 + broad * 0.27 + grain * 0.07);
                float blend = saturate(0.5 + (aggregate - 0.5) * (0.72 + _DetailStrength * 1.65));
                half3 albedo = lerp(_SecondaryColor.rgb, _BaseColor.rgb, blend);

                // Paving joints and cast-concrete seams are generated in the
                // shader. The material never samples an asphalt or wall image.
                if (_Mode > 0.5 && _Mode < 1.5)
                {
                    float2 tile = abs(frac(plane * 0.46) - 0.5);
                    float joint = smoothstep(0.472, 0.497, max(tile.x, tile.y));
                    float stagger = step(0.5, frac(floor(plane.y * 0.46) * 0.5));
                    float verticalJoint = smoothstep(0.478, 0.498, abs(frac(plane.x * 0.46 + stagger * 0.5) - 0.5));
                    albedo *= lerp(1.0h, 0.72h, max(joint * 0.45, verticalJoint * 0.5));
                }
                else if (_Mode > 1.5)
                {
                    float floorJoint = smoothstep(0.485, 0.5, abs(frac(input.positionWS.y / 3.35) - 0.5));
                    float formwork = smoothstep(0.493, 0.5, abs(frac(plane.x * 0.28) - 0.5));
                    albedo *= lerp(1.0h, 0.88h, floorJoint * 0.36 + formwork * 0.08);
                }

                if (_Mode < 1.5 && abs(normalWS.y) > 0.72h)
                {
                    float epsilon = 0.045;
                    float dx = Fbm((plane + float2(epsilon, 0.0)) * _DetailScale) - fine;
                    float dz = Fbm((plane + float2(0.0, epsilon)) * _DetailScale) - fine;
                    normalWS = normalize(normalWS + half3(-dx, 0.0h, -dz) * (_DetailStrength * 0.62));
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
                half4 color = UniversalFragmentPBR(
                    inputData, albedo, _Metallic, half3(0, 0, 0),
                    _Smoothness, occlusion, half3(0, 0, 0), 1.0h);
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
