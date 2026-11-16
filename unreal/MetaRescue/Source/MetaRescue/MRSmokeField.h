#pragma once
#include "CoreMinimal.h"

// A renderer-independent plume. Positions, lengths and extinction use cm;
// optical depth is dimensionless. Wind displaces older, higher smoke while
// the emitting source stays fixed. The renderer consumes these same bounds.
struct FMRSmokeVolume
{
    FString EventId;
    FVector Source=FVector::ZeroVector;
    FVector WindCmPerSecond=FVector::ZeroVector;
    double HeightCm=3000;
    double RadiusCm=1800;
    double RadiusGrowth=.12;
    double RiseCmPerSecond=150;
    double ExtinctionPerCm=.0035;
    double Strength=1;

    bool IsValid() const
    {
        return !Source.ContainsNaN()&&!WindCmPerSecond.ContainsNaN()&&
            FMath::IsFinite(HeightCm)&&HeightCm>0&&FMath::IsFinite(RadiusCm)&&RadiusCm>0&&
            FMath::IsFinite(RadiusGrowth)&&RadiusGrowth>=0&&FMath::IsFinite(RiseCmPerSecond)&&RiseCmPerSecond>0&&
            FMath::IsFinite(ExtinctionPerCm)&&ExtinctionPerCm>=0&&FMath::IsFinite(Strength)&&Strength>=0&&Strength<=1;
    }

    FVector CenterAt(double Height) const
    {
        const double H=FMath::Clamp(Height,0.,HeightCm);
        const double Age=H/RiseCmPerSecond;
        return Source+FVector(WindCmPerSecond.X*Age,WindCmPerSecond.Y*Age,H);
    }

    FBox Bounds() const
    {
        const FVector Top=CenterAt(HeightCm);
        const double Radius=RadiusCm+RadiusGrowth*HeightCm;
        return FBox(FVector(FMath::Min(Source.X,Top.X)-Radius,FMath::Min(Source.Y,Top.Y)-Radius,Source.Z),
                    FVector(FMath::Max(Source.X,Top.X)+Radius,FMath::Max(Source.Y,Top.Y)+Radius,Source.Z+HeightCm));
    }

    double Extinction(const FVector& Point) const
    {
        if(!IsValid()||Point.ContainsNaN())return 0;
        const double H=Point.Z-Source.Z;
        if(H<=0||H>=HeightCm)return 0;
        const double Radius=RadiusCm+RadiusGrowth*H;
        const double Q=FVector::DistSquared2D(Point,CenterAt(H))/FMath::Square(Radius);
        if(Q>=1)return 0;
        const double Feather=FMath::Min3(1.,H/FMath::Min(100.,HeightCm*.2),
            (HeightCm-H)/FMath::Min(300.,HeightCm*.2));
        return ExtinctionPerCm*Strength*FMath::Square(1-Q)*Feather;
    }

    double OpticalDepth(const FVector& Start,const FVector& End) const
    {
        if(!IsValid()||Start.ContainsNaN()||End.ContainsNaN())return 0;
        const FVector Delta=End-Start;
        const double Distance=Delta.Length();
        if(Distance<1.e-8)return 0;
        const FBox Box=Bounds();
        double From=0,To=1;
        for(int32 Axis=0;Axis<3;++Axis)
        {
            if(FMath::Abs(Delta[Axis])<1.e-10)
            {
                if(Start[Axis]<Box.Min[Axis]||Start[Axis]>Box.Max[Axis])return 0;
                continue;
            }
            const double A=(Box.Min[Axis]-Start[Axis])/Delta[Axis];
            const double B=(Box.Max[Axis]-Start[Axis])/Delta[Axis];
            From=FMath::Max(From,FMath::Min(A,B));To=FMath::Min(To,FMath::Max(A,B));
            if(From>=To)return 0;
        }
        // Clip before sampling: a long clear approach must not skip a narrow
        // plume. Simpson integration bounds work per volume, not per camera.
        int32 Steps=FMath::Clamp(FMath::CeilToInt(Distance*(To-From)/75.),2,256);
        if(Steps%2)++Steps;
        const double Step=(To-From)/Steps;
        double Sum=Extinction(Start+Delta*From)+Extinction(Start+Delta*To);
        for(int32 I=1;I<Steps;++I)Sum+=(I%2?4.:2.)*Extinction(Start+Delta*(From+I*Step));
        return FMath::Max(0.,Sum*Step*Distance/3.);
    }

    static double Transmittance(const TArray<FMRSmokeVolume>& Volumes,const FVector& Start,const FVector& End)
    {
        if(Start.ContainsNaN()||End.ContainsNaN())return 0;
        double Depth=0;
        for(const auto& Volume:Volumes)
        {
            Depth+=Volume.OpticalDepth(Start,End);
            if(Depth>=30)return 0;
        }
        return FMath::Exp(-Depth);
    }
};
