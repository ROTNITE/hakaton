#pragma once

// Authoritative defaults for the 3D environment. Percent chance per 30 model
// seconds over the whole district, in the same order as benchmark v0.3.
// Change these values and rebuild; command-line overrides are for experiments.
namespace MRDistrictSettings
{
inline constexpr float ProbabilityPct[8] = {12,12,10,14,14,15,12,20};
inline constexpr double WindowSeconds = 30;
inline constexpr double HorizonSeconds = 480;
inline constexpr int32 DefaultSeed = 20261109;
inline constexpr float CellCm = 500;
inline constexpr float MudCost = 2.25f;
inline constexpr float DamagedRoadCost = 1.90f;
inline constexpr float SmokeQuality = .52f;
inline constexpr float FogQuality = .62f;
inline constexpr double SmokeSeconds = 90;
inline constexpr double FogSeconds = 100;
inline constexpr double FireSmokeSeconds = 70;
inline constexpr float UnsafeWaterCm = 25;
inline constexpr float MaximumFloodCm = 42;
inline constexpr float WaterRiseCmPerSecond = .8f;
inline constexpr float GroundClearanceCm = 35;
inline constexpr float DroneClearanceCm = 100;
}
