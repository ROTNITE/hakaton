#pragma once
#include "CoreMinimal.h"

// Permanent, delivered knowledge only. Sensor collection, radio delivery and
// renderer masking remain outside this container; cameras cannot reveal cells.
class FMRExplorationGrid
{
public:
    bool Reset(int32 InWidth,int32 InHeight,double InCellCm=500,FVector2D InOriginCm=FVector2D::ZeroVector)
    {
        Open.Empty();Width=Height=Count=Revision=0;
        if(InWidth<1||InHeight<1||InWidth>384||InHeight>384||int64(InWidth)*InHeight>100000||
           !FMath::IsFinite(InCellCm)||InCellCm<=0||InOriginCm.ContainsNaN())return false;
        Width=InWidth;Height=InHeight;CellCm=InCellCm;OriginCm=InOriginCm;Open.Init(false,Width*Height);return true;
    }
    bool IsValid(FIntPoint Cell) const {return Cell.X>=0&&Cell.Y>=0&&Cell.X<Width&&Cell.Y<Height;}
    bool IsOpen(FIntPoint Cell) const {return IsValid(Cell)&&Open[Cell.Y*Width+Cell.X];}
    bool IsOpen(const FVector& PositionCm) const
    {
        return !PositionCm.ContainsNaN()&&PositionCm.X>=OriginCm.X&&PositionCm.Y>=OriginCm.Y&&
            PositionCm.X<OriginCm.X+Width*CellCm&&PositionCm.Y<OriginCm.Y+Height*CellCm&&IsOpen(CellAt(PositionCm));
    }
    FIntPoint CellAt(FVector P) const
    {return FIntPoint(FMath::FloorToInt((P.X-OriginCm.X)/CellCm),FMath::FloorToInt((P.Y-OriginCm.Y)/CellCm));}
    FVector Center(FIntPoint Cell) const
    {return FVector(OriginCm.X+(Cell.X+.5)*CellCm,OriginCm.Y+(Cell.Y+.5)*CellCm,0);}
    int32 Reveal(const TArray<FIntPoint>& Cells)
    {
        int32 Added=0;
        for(const auto& Cell:Cells)
        {
            if(!IsValid(Cell))continue;
            const int32 I=Cell.Y*Width+Cell.X;
            if(!Open[I]){Open[I]=true;++Added;}
        }
        Count+=Added;if(Added>0)++Revision;
        return Added;
    }
    int32 RevealBase(const FBox& BaseCm)
    {
        if(!BaseCm.IsValid||BaseCm.Min.ContainsNaN()||BaseCm.Max.ContainsNaN())return 0;
        // Base boundaries may coincide with cell edges; use a half-open box.
        const int32 MinX=FMath::Clamp(FMath::FloorToInt((BaseCm.Min.X-OriginCm.X)/CellCm),0,Width);
        const int32 MinY=FMath::Clamp(FMath::FloorToInt((BaseCm.Min.Y-OriginCm.Y)/CellCm),0,Height);
        const int32 MaxX=FMath::Clamp(FMath::CeilToInt((BaseCm.Max.X-OriginCm.X)/CellCm),0,Width);
        const int32 MaxY=FMath::Clamp(FMath::CeilToInt((BaseCm.Max.Y-OriginCm.Y)/CellCm),0,Height);
        TArray<FIntPoint> Cells;
        for(int32 Y=MinY;Y<MaxY;++Y)for(int32 X=MinX;X<MaxX;++X)Cells.Add(FIntPoint(X,Y));
        return Reveal(Cells);
    }
    // Sorted row spans: (row, first column, exclusive last column). Complete
    // snapshots support reconnection without depending on missed UI deltas.
    TArray<FIntVector> RowSpans() const
    {
        TArray<FIntVector> Spans;
        for(int32 Y=0;Y<Height;++Y)for(int32 X=0;X<Width;)
        {
            if(!Open[Y*Width+X]){++X;continue;}
            const int32 Start=X;
            while(X<Width&&Open[Y*Width+X])++X;
            Spans.Emplace(Y,Start,X);
        }
        return Spans;
    }
    int32 GetWidth() const {return Width;}
    int32 GetHeight() const {return Height;}
    int32 OpenCount() const {return Count;}
    int32 GetRevision() const {return Revision;}
    double GetCellCm() const {return CellCm;}
    FVector2D GetOriginCm() const {return OriginCm;}
private:
    int32 Width=0,Height=0,Count=0,Revision=0;
    double CellCm=500;
    FVector2D OriginCm=FVector2D::ZeroVector;
    TBitArray<> Open;
};
