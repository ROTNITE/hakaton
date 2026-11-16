#pragma once
#include "MRExplorationGrid.h"

struct FMRSeenSurface
{
    FIntPoint Cell=FIntPoint::ZeroValue;
    FVector PointCm=FVector::ZeroVector,Normal=FVector::UpVector;
    double Quality=0,ObservedAt=-1,ReceivedAt=-1;
    FString Source;
    uint32 SurfaceComponent=0; // Private renderer identity, never a discovered object catalogue.
    bool Water=false;
};

// Fixed upper bound: one immutable last-delivered surface observation per cell.
// Collection does not call Apply; a lost/expired radio packet changes nothing.
class FMRExplorationMemory
{
public:
    FMRExplorationGrid Grid;
    bool Reset(int32 Width,int32 Height,double CellCm,FVector2D Origin)
    {
        Samples.Empty();Revision=0;
        if(!Grid.Reset(Width,Height,CellCm,Origin))return false;
        Samples.SetNum(Width*Height);return true;
    }
    int32 Apply(const TArray<FMRSeenSurface>& Delivered)
    {
        TArray<FIntPoint> Cells;int32 Updated=0;
        for(const auto& Sample:Delivered)
        {
            if(!Grid.IsValid(Sample.Cell)||Sample.PointCm.ContainsNaN()||Sample.Normal.ContainsNaN()||
               Grid.CellAt(Sample.PointCm)!=Sample.Cell||!FMath::IsFinite(Sample.Quality)||Sample.Quality<.15||Sample.Quality>1||
               !FMath::IsFinite(Sample.ObservedAt)||!FMath::IsFinite(Sample.ReceivedAt)||
               Sample.ObservedAt<0||Sample.ReceivedAt<Sample.ObservedAt||Sample.Source.IsEmpty())continue;
            const int32 I=Sample.Cell.Y*Grid.GetWidth()+Sample.Cell.X;const auto& Existing=Samples[I];
            if(Existing.IsSet()&&(Existing.GetValue().ObservedAt>Sample.ObservedAt||
                (Existing.GetValue().ObservedAt==Sample.ObservedAt&&Existing.GetValue().Quality>=Sample.Quality)))continue;
            Samples[I]=Sample;Cells.Add(Sample.Cell);++Updated;
        }
        Grid.Reveal(Cells);if(Updated)++Revision;return Updated;
    }
    const FMRSeenSurface* Last(FIntPoint Cell) const
    {
        if(!Grid.IsValid(Cell))return nullptr;
        const auto& Entry=Samples[Cell.Y*Grid.GetWidth()+Cell.X];return Entry.IsSet()?&Entry.GetValue():nullptr;
    }
    int32 GetRevision() const {return Revision;}
private:
    TArray<TOptional<FMRSeenSurface>> Samples;
    int32 Revision=0;
};
