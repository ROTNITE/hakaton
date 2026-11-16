#pragma once
#include "CoreMinimal.h"
#include "Dom/JsonObject.h"

// Public initial geometry in centimetres. No water, events, renderer or sensor
// state enters this function; contracts/urban_terrain.py is its metre analogue.
class FMRGradedTerrain
{
public:
    bool Read(const TSharedPtr<FJsonObject>& Data)
    {
        Enabled=false;Pads.Empty();Depressions.Empty();
        if(!Data)return true;
        FString Format;const TSharedPtr<FJsonObject>* Base=nullptr;
        if(!Data->TryGetStringField(TEXT("format"),Format)||Format!=TEXT("metarescue.graded-terrain.v1")||
            !Data->TryGetObjectField(TEXT("base"),Base)||!Box(*Base,BaseBounds)||
            !Data->TryGetNumberField(TEXT("base_elevation_m"),Elevation)||!FMath::IsFinite(Elevation)||Elevation<0||Elevation>10||
            !Data->TryGetNumberField(TEXT("grade_width_m"),Grade)||!FMath::IsFinite(Grade)||Grade<20||Grade>100)return false;
        Elevation*=100;Grade*=100;
        const TSharedPtr<FJsonObject>* Ramp=nullptr;
        if(!Data->TryGetObjectField(TEXT("ramp"),Ramp)||!Box(*Ramp,RampBounds))return false;
        if(!FMath::IsNearlyEqual(RampBounds.Min.X,BaseBounds.Max.X,1.e-5)||
           !FMath::IsNearlyEqual(RampBounds.GetSize().X,Grade,1.e-5))return false;
        const TArray<TSharedPtr<FJsonValue>>* Areas=nullptr;
        if(!Data->TryGetArrayField(TEXT("pads"),Areas)||Areas->Num()>20000)return false;
        for(const auto& Value:*Areas)
        {
            if(Value->Type!=EJson::Object)return false;
            FPad Pad;const auto Row=Value->AsObject();
            if(!Box(Row,Pad.Bounds)||!Row->TryGetNumberField(TEXT("elevation_m"),Pad.Height)||
                !FMath::IsFinite(Pad.Height)||Pad.Height< -10||Pad.Height>10)return false;
            Pad.Height*=100;const auto Range=Pad.Bounds.ExpandBy(100);
            for(int32 X=FMath::FloorToInt(Range.Min.X/3200);X<=FMath::FloorToInt(Range.Max.X/3200);++X)
                for(int32 Y=FMath::FloorToInt(Range.Min.Y/3200);Y<=FMath::FloorToInt(Range.Max.Y/3200);++Y)
                    Pads.FindOrAdd(FIntPoint(X,Y)).Add(Pad);
        }
        if(Data->TryGetArrayField(TEXT("depressions"),Areas))for(const auto& Value:*Areas)
        {
            if(Value->Type!=EJson::Object)return false;
            FPad Pad;const auto Row=Value->AsObject();
            if(!Box(Row,Pad.Bounds)||!Row->TryGetNumberField(TEXT("elevation_m"),Pad.Height)||
                !FMath::IsFinite(Pad.Height)||Pad.Height< -20||Pad.Height>0)return false;
            Pad.Height*=100;Depressions.Add(Pad);
        }
        Enabled=true;return true;
    }

    double Height(FVector P) const
    {
        if(!Enabled)return 0;
        for(const auto& Area:Depressions)if(Area.Bounds.IsInsideXY(P))return Area.Height;
        double Result=Elevation*FMath::Max(0.,1.-Distance(P,BaseBounds)/Grade);
        const auto* Nearby=Pads.Find(FIntPoint(FMath::FloorToInt(P.X/3200),FMath::FloorToInt(P.Y/3200)));
        if(!Nearby)return Result;
        double Closest=100;const FPad* Chosen=nullptr;
        for(const auto& Pad:*Nearby)
        {const double Gap=Distance(P,Pad.Bounds);if(Gap<Closest){Closest=Gap;Chosen=&Pad;}}
        if(Chosen)Result+=(Chosen->Height-Result)*(1-FMath::SmoothStep(0.,100.,Closest));
        return Result;
    }

    bool IsEnabled() const {return Enabled;}
private:
    struct FPad {FBox Bounds;double Height=0;};
    bool Enabled=false;
    FBox BaseBounds=FBox(ForceInit);
    FBox RampBounds=FBox(ForceInit);
    double Elevation=0,Grade=4500;
    TMap<FIntPoint,TArray<FPad>> Pads;
    TArray<FPad> Depressions;
    static double Distance(FVector P,const FBox& B)
    {return FMath::Sqrt(FMath::Square(FMath::Max3(B.Min.X-P.X,0.,P.X-B.Max.X))+FMath::Square(FMath::Max3(B.Min.Y-P.Y,0.,P.Y-B.Max.Y)));}
    static bool Box(const TSharedPtr<FJsonObject>& Row,FBox& Result)
    {
        const TArray<TSharedPtr<FJsonValue>> *Low=nullptr,*High=nullptr;
        if(!Row||!Row->TryGetArrayField(TEXT("min"),Low)||!Row->TryGetArrayField(TEXT("max"),High)||Low->Num()!=2||High->Num()!=2)return false;
        FVector A=FVector::ZeroVector,B=FVector::ZeroVector;
        for(int32 I=0;I<2;++I)
        {
            double X,Y;if(!(*Low)[I]->TryGetNumber(X)||!(*High)[I]->TryGetNumber(Y)||!FMath::IsFinite(X)||!FMath::IsFinite(Y)||
                X>=Y||FMath::Abs(X)>20000||FMath::Abs(Y)>20000)return false;
            A[I]=X*100;B[I]=Y*100;
        }
        Result=FBox(A,B);return true;
    }
};
