// Custom material body. Centimetres and extinction/cm match FMRSmokeVolume.
float3 Top = Source + float3(Wind.xy * Shape.x / max(Rise, 1), Shape.x);
float Radius = Shape.y + Shape.z * Shape.x;
float3 Lo = float3(min(Source.xy, Top.xy) - Radius, Source.z);
float3 Hi = float3(max(Source.xy, Top.xy) + Radius, Source.z + Shape.x);
float3 Delta = Surface - Camera;
float SurfaceDistance = length(Delta);
float3 Ray = Delta / max(SurfaceDistance, .001);
bool Inside = all(Camera >= Lo) && all(Camera <= Hi);
// Draw a single integration, including when the camera enters the volume.
if ((Inside && Side > 0) || (!Inside && Side < 0)) return 0;
float3 SafeRay = lerp(-1.0, 1.0, step(0.0, Ray)) * max(abs(Ray), .000001);
float3 A = (Lo - Camera) / SafeRay;
float3 B = (Hi - Camera) / SafeRay;
float3 Near = min(A, B), Far = max(A, B);
float Start = max(0, max(Near.x, max(Near.y, Near.z)));
float Finish = min(Far.x, min(Far.y, Far.z));
// Scene/pixel depth share the projection. This ratio converts both to the
// actual oblique ray distance, so opaque walls stop the smoke integration.
Finish = min(Finish, SceneZ * SurfaceDistance / max(PixelZ, .001));
if (Finish <= Start || Shape.x <= 0 || Strength <= 0) return 0;
const int Steps = 48;
float StepCm = (Finish - Start) / Steps;
float OpticalDepth = 0;
[unroll] for (int i = 0; i < Steps; ++i)
{
    float3 P = Camera + Ray * (Start + (i + .5) * StepCm);
    float Height = P.z - Source.z;
    float3 Center = Source + float3(Wind.xy * Height / max(Rise, 1), Height);
    float LocalRadius = Shape.y + Shape.z * Height;
    float2 XY = (P.xy - Center.xy) / max(LocalRadius, 1);
    float Radial = saturate(1 - dot(XY, XY));
    float Feather = saturate(min(Height / max(min(100, Shape.x * .2), .001),
        (Shape.x - Height) / max(min(300, Shape.x * .2), .001)));
    OpticalDepth += Extinction * Strength * Radial * Radial * Feather * StepCm;
}
return saturate(1 - exp(-OpticalDepth));
