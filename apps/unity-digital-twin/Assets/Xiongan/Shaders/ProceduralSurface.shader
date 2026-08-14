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
        LOD 250

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

            float Noise(float2 p)
            {
                float2 i = floor(p);
                float2 f = frac(p);
                f = f * f * (3.0 - 2.0 * f);
                return lerp(lerp(Hash21(i), Hash21(i + float2(1,0)), f.x),
                            lerp(Hash21(i + float2(0,1)), Hash21(i + 1), f.x), f.y);
            }

            Varyings Vert(Attributes input)
            {
                Varyings output;
                VertexPositionInputs pos = GetVertexPositionInputs(input.positionOS.xyz);
                output.positionCS = pos.positionCS;
                output.positionWS = pos.positionWS;
                output.normalWS = TransformObjectToWorldNormal(input.normalOS);
                output.fogFactor = ComputeFogFactor(pos.positionCS.z);
                output.shadowCoord = TransformWorldToShadowCoord(pos.positionWS);
                return output;
            }

            half4 Frag(Varyings input) : SV_Target
            {
                float2 plane = input.positionWS.xz;
                if (_Mode > 1.5) plane = input.positionWS.xy + input.positionWS.zy * 0.31;
                float fine = Noise(plane * _DetailScale);
                float broad = Noise(plane * (_DetailScale * 0.13) + 17.7);
                float aggregate = saturate(fine * 0.68 + broad * 0.32);
                float blend = saturate(0.5 + (aggregate - 0.5) * (1.0 + _DetailStrength * 3.0));
                half3 albedo = lerp(_SecondaryColor.rgb, _BaseColor.rgb, blend);

                if (_Mode > 0.5 && _Mode < 1.5)
                {
                    float2 tile = abs(frac(plane * 0.42) - 0.5);
                    float joint = smoothstep(0.465, 0.495, max(tile.x, tile.y));
                    albedo *= lerp(1.0h, 0.79h, joint);
                }
                if (_Mode > 1.5)
                {
                    float floorBand = smoothstep(0.46, 0.5, abs(frac(input.positionWS.y * 0.295) - 0.5));
                    albedo *= lerp(1.0h, 0.91h, floorBand * 0.45);
                }

                half3 n = normalize(input.normalWS);
                if (_Mode < 1.5 && abs(n.y) > 0.72h)
                {
                    float detailX = Noise((plane + float2(0.065, 0.0)) * _DetailScale);
                    float detailY = Noise((plane + float2(0.0, 0.065)) * _DetailScale);
                    float bump = _DetailStrength * 0.34;
                    n = normalize(n + half3((fine - detailX) * bump, 0, (fine - detailY) * bump));
                }
                Light light = GetMainLight(input.shadowCoord);
                half ndl = saturate(dot(n, light.direction));
                half3 ambient = max(SampleSH(n), half3(0.15h, 0.16h, 0.145h)) * albedo;
                half3 diffuse = albedo * light.color * ndl * light.distanceAttenuation * light.shadowAttenuation;
                half3 viewDir = normalize(GetWorldSpaceViewDir(input.positionWS));
                half3 halfDir = normalize(light.direction + viewDir);
                half specPower = lerp(10.0h, 120.0h, _Smoothness);
                half spec = pow(saturate(dot(n, halfDir)), specPower) * lerp(0.05h, 0.72h, _Smoothness);
                half3 specular = light.color * spec * light.shadowAttenuation * lerp(0.25h, 1.0h, _Metallic);
                half3 color = ambient * 1.06h + diffuse + specular;
                color = MixFog(color, input.fogFactor);
                return half4(color, 1);
            }
            ENDHLSL
        }

        UsePass "Universal Render Pipeline/Lit/ShadowCaster"
        UsePass "Universal Render Pipeline/Lit/DepthOnly"
    }
}
