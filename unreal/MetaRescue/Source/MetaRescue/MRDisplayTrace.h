#pragma once
#include "CoreMinimal.h"

struct FMRDisplayPoint
{
    FVector Position;
    double Time=0;
    bool Connected=false;
};

// UI-owned bounded history. It never participates in physics, sensing or decisions.
class FMRDisplayTrace
{
public:
    static constexpr int32 MaximumPoints=2048;
    TArray<FMRDisplayPoint> Points;
    double LastSample=-1;
    FVector LastPosition=FVector::ZeroVector;
    void Add(double Time,const FVector& Position,bool Delivered=false)
    {
        if(!FMath::IsFinite(Time)||Position.ContainsNaN()||Time<=LastSample+1.e-8)return;
        const double Gap=LastSample<0?0:Time-LastSample;
        const double Jump=LastSample<0?0:FVector::Distance(Position,LastPosition);
        const bool Continuous=LastSample>=0&&Gap<=(Delivered?1.75:.35)&&Jump<=FMath::Max(200.,2000.*Gap);
        LastSample=Time;LastPosition=Position;
        if(!Points.IsEmpty()&&Continuous&&FVector::DistSquared(Points.Last().Position,Position)<100)return;
        if(Points.Num()>=MaximumPoints)Points.RemoveAt(0,256,EAllowShrinking::No);
        Points.Add({Position,Time,Continuous&&!Points.IsEmpty()});
    }
    void Reset(){Points.Reset();LastSample=-1;LastPosition=FVector::ZeroVector;}
};

inline FLinearColor MRDisplayColor(const FString& Id)
{
    uint32 Hash=2166136261u;
    for(TCHAR Character:Id){Hash^=uint32(Character);Hash*=16777619u;}
    Hash^=Hash>>16;Hash*=0x7feb352du;Hash^=Hash>>15;
    return FLinearColor::MakeFromHSV8(uint8(Hash&255),uint8(140+(Hash>>8)%65),245);
}
