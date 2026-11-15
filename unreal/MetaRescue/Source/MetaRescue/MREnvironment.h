#pragma once
#include "CoreMinimal.h"
#include "MRDistrictSettings.h"

enum class EMRDisturbance : uint8 { Collapse,Fire,Flood,Mud,RoadDamage,Smoke,LowVisibility,NewTarget };
const TCHAR* MRDisturbanceName(EMRDisturbance Kind);

struct FMREventSite
{
    FString Id;
    EMRDisturbance Kind;
    FVector Position;
    // Eligible surface cells are authored independently of agents and policies.
    TArray<FIntPoint> Cells;
};

struct FMRDisturbance
{
    FString Id,ParentId,SiteId,Rejection;
    EMRDisturbance Kind=EMRDisturbance::Collapse;
    double Time=0;
    // Negative means the legacy/default lifetime. Core stores explicit absolute
    // expiry times; these values remain simulator truth until an observation.
    double ExpiresAt=-1,VisibilityExpiresAt=-1;
    float VisibilityTopCm=TNumericLimits<float>::Max();
    FVector Source=FVector::ZeroVector;
    TArray<FIntPoint> Cells;
    int32 TargetId=-1;
    bool bPropagation=false;
};

// No actor, renderer, route planner, or sensor RNG is referenced here.
class FMRDistrictEnvironment
{
public:
    TArray<FMRDisturbance> Tape;
    TArray<FMRDisturbance> Applied;
    float Probabilities[8];
    double Horizon=MRDistrictSettings::HorizonSeconds;
    double Time=0;
    int32 Revision=0,Index=0,Seed=MRDistrictSettings::DefaultSeed;
    FString Mode=TEXT("random");
    FMRDistrictEnvironment();
    void Generate(const TArray<FMREventSite>& Sites);
    void ResetApplied();
    TArray<FMRDisturbance> Advance(double NewTime);
    float Cost(const FVector& P,bool IncludeWater=true) const;
    float Depth(const FVector& P) const;
    float Visibility(const FVector& P) const;
    bool Unsafe(const FVector& P,bool IncludeWater=true) const;
    bool IsActive(const FMRDisturbance& Event) const;
    double ActiveUntil(const FMRDisturbance& Event) const;
    double VisibilityUntil(const FMRDisturbance& Event) const;
    bool HasEffect(EMRDisturbance Kind,const FVector& P) const;
    const FMRDisturbance* FindApplied(const FString& Id) const;
    bool HasHistoryAt(FIntPoint Cell) const {return VisibleCells.Contains(Cell);}
    double NextBoundary() const;
    static bool Protected(const FVector& P);
    static FIntPoint Cell(const FVector& P);
    static FVector Center(FIntPoint Cell);
private:
    TMap<FIntPoint,TArray<int32>> AppliedCells,VisibleCells;
    TMap<FString,int32> AppliedIds;
    void IndexApplied(int32 EventIndex);
};
