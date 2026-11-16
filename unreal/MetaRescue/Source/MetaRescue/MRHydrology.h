#pragma once
#include "CoreMinimal.h"

// Local-inertial, conservative storage grid in metres and model seconds.
// Formulation: Bates, Horritt & Fewtrell (2010), doi:10.1016/j.jhydrol.2010.03.027.
// This is a bounded simulation model, not a certified hydraulic predictor.
// Actor, renderer, controller knowledge and event scheduling are separate.
class FMRHydrology
{
public:
    bool Configure(int32 InWidth,int32 InHeight,double InCellM,const TArray<double>& InBed,
        const TBitArray<>& InSolid,const TArray<double>& InDepth)
    {
        Healthy=false;
        if(InWidth<1||InHeight<1||InWidth>384||InHeight>384||int64(InWidth)*InHeight>100000||
           !FMath::IsFinite(InCellM)||InCellM<.5||InCellM>20||InBed.Num()!=InWidth*InHeight||
           InSolid.Num()!=InBed.Num()||InDepth.Num()!=InBed.Num())return false;
        for(int32 I=0;I<InBed.Num();++I)
            if(!FMath::IsFinite(InBed[I])||InBed[I]<-20||InBed[I]>100||
               !FMath::IsFinite(InDepth[I])||InDepth[I]<0||InDepth[I]>20||(InSolid[I]&&InDepth[I]>0))return false;
        Width=InWidth;Height=InHeight;CellM=InCellM;InitialBed=InBed;InitialDepth=InDepth;Solid=InSolid;
        InitialCrestX.Init(-MAX_dbl,FMath::Max(0,Width-1)*Height);
        InitialCrestY.Init(-MAX_dbl,Width*FMath::Max(0,Height-1));
        Reset();return true;
    }

    void Reset()
    {
        Bed=InitialBed;Depth=InitialDepth;
        Qx.Init(0,FMath::Max(0,Width-1)*Height);Qy.Init(0,Width*FMath::Max(0,Height-1));
        CrestX=InitialCrestX;CrestY=InitialCrestY;
        Roughness.Init(.035,Depth.Num());Outgoing.Init(0,Depth.Num());Limiter.Init(1,Depth.Num());
        Boundaries.Empty();Drains.Empty();InitialVolumeM3=VolumeM3();
        InflowM3=OutflowM3=DrainedM3=NumericalCorrectionM3=Elapsed=0;
        Healthy=Depth.Num()>0;
    }

    int32 Index(int32 X,int32 Y) const {return X>=0&&X<Width&&Y>=0&&Y<Height?Y*Width+X:INDEX_NONE;}
    int32 GetWidth() const {return Width;}
    int32 GetHeight() const {return Height;}
    double GetCellM() const {return CellM;}
    double DepthM(int32 I) const {return Depth.IsValidIndex(I)?Depth[I]:0;}
    double BedM(int32 I) const {return Bed.IsValidIndex(I)?Bed[I]:0;}
    double StageM(int32 I) const {return BedM(I)+DepthM(I);}
    double Time() const {return Elapsed;}
    bool IsHealthy() const {return Healthy;}

    bool SetBoundaryStage(int32 I,double Stage)
    {
        if(!Depth.IsValidIndex(I)||Solid[I]||!FMath::IsFinite(Stage)||Stage<Bed[I]-20||Stage>Bed[I]+20)return false;
        Boundaries.Add(I,Stage);return true;
    }
    void ClearBoundaries(){Boundaries.Empty();}
    bool SetDrain(int32 I,double CapacityM3PerSecond)
    {
        if(!Depth.IsValidIndex(I)||Solid[I]||!FMath::IsFinite(CapacityM3PerSecond)||CapacityM3PerSecond<0||CapacityM3PerSecond>100)return false;
        Drains.Add(I,CapacityM3PerSecond);return true;
    }
    bool SetRoughness(int32 I,double ManningN)
    {
        if(!Depth.IsValidIndex(I)||!FMath::IsFinite(ManningN)||ManningN<.005||ManningN>1)return false;
        Roughness[I]=ManningN;return true;
    }
    bool SetBed(int32 I,double ElevationM)
    {
        if(!Depth.IsValidIndex(I)||!FMath::IsFinite(ElevationM)||ElevationM<-20||ElevationM>100)return false;
        // Subsidence changes storage geometry, not the amount of water.
        Bed[I]=ElevationM;return true;
    }
    bool SetCrestX(int32 X,int32 Y,double ElevationM,bool Persistent=false)
    {
        if(X<0||X>=Width-1||Y<0||Y>=Height||!FMath::IsFinite(ElevationM))return false;
        const int32 I=Y*(Width-1)+X;CrestX[I]=ElevationM;
        if(Persistent)InitialCrestX[I]=ElevationM;return true;
    }
    bool SetCrestY(int32 X,int32 Y,double ElevationM,bool Persistent=false)
    {
        if(X<0||X>=Width||Y<0||Y>=Height-1||!FMath::IsFinite(ElevationM))return false;
        const int32 I=Y*Width+X;CrestY[I]=ElevationM;
        if(Persistent)InitialCrestY[I]=ElevationM;return true;
    }

    FVector CurrentMPerSecond(int32 I) const
    {
        if(!Depth.IsValidIndex(I)||Solid[I]||Depth[I]<.02)return FVector::ZeroVector;
        const int32 X=I%Width,Y=I/Width;
        const double U=((X>0?Qx[Y*(Width-1)+X-1]:0)+(X+1<Width?Qx[Y*(Width-1)+X]:0))*.5/Depth[I];
        const double V=((Y>0?Qy[(Y-1)*Width+X]:0)+(Y+1<Height?Qy[Y*Width+X]:0))*.5/Depth[I];
        return FVector(U,V,0);
    }

    double VolumeM3() const
    {
        double Sum=0;for(double H:Depth)Sum+=H;
        return Sum*CellM*CellM;
    }
    double BalanceErrorM3() const
    {return VolumeM3()-(InitialVolumeM3+InflowM3-OutflowM3-DrainedM3+NumericalCorrectionM3);}
    double AddedM3() const {return InflowM3;}
    double RemovedM3() const {return OutflowM3+DrainedM3;}

    bool Advance(double Seconds)
    {
        if(!Healthy||!FMath::IsFinite(Seconds)||Seconds<0||Seconds>600)return false;
        double Remaining=Seconds;int32 Steps=0;
        while(Remaining>1.e-10)
        {
            EnforceBoundaries();
            double MaxDepth=0,Speed=0;
            for(int32 I=0;I<Depth.Num();++I)
            {
                MaxDepth=FMath::Max(MaxDepth,Depth[I]);
                if(Depth[I]>.05)Speed=FMath::Max(Speed,CurrentMPerSecond(I).Size());
            }
            const double Step=FMath::Min3(Remaining,.25,.4*CellM/FMath::Max(.1,FMath::Sqrt(9.81*MaxDepth)+Speed));
            if(++Steps>100000||!FMath::IsFinite(Step)||Step<1.e-8||!Substep(Step)){Healthy=false;return false;}
            Remaining-=Step;Elapsed+=Step;
        }
        return true;
    }

private:
    int32 Width=0,Height=0;
    double CellM=5,Elapsed=0,InitialVolumeM3=0,InflowM3=0,OutflowM3=0,DrainedM3=0,NumericalCorrectionM3=0;
    bool Healthy=false;
    TArray<double> InitialBed,InitialDepth,InitialCrestX,InitialCrestY,Bed,Depth,Qx,Qy,CrestX,CrestY,Roughness,Outgoing,Limiter;
    TBitArray<> Solid;
    TMap<int32,double> Boundaries,Drains;

    void EnforceBoundaries()
    {
        for(const auto& Pair:Boundaries)
        {
            const int32 I=Pair.Key;
            const double Next=FMath::Max(0.,Pair.Value-Bed[I]);
            const double Delta=(Next-Depth[I])*CellM*CellM;
            if(Delta>=0)InflowM3+=Delta;else OutflowM3-=Delta;
            Depth[I]=Next;
        }
    }

    double Discharge(int32 A,int32 B,double Previous,double Crest,double Dt) const
    {
        if(Solid[A]||Solid[B])return 0;
        const double SurfaceA=Bed[A]+Depth[A],SurfaceB=Bed[B]+Depth[B];
        const double FlowDepth=FMath::Max(SurfaceA,SurfaceB)-FMath::Max3(Bed[A],Bed[B],Crest);
        if(FlowDepth<=1.e-5)return 0;
        const double N=(Roughness[A]+Roughness[B])*.5;
        const double Friction=1+9.81*Dt*N*N*FMath::Abs(Previous)/FMath::Pow(FlowDepth,7./3.);
        return (Previous-9.81*FlowDepth*Dt*(SurfaceB-SurfaceA)/CellM)/Friction;
    }

    bool Substep(double Dt)
    {
        for(double& Value:Outgoing)Value=0;
        auto Accumulate=[&](int32 A,int32 B,double Q)
        {Outgoing[Q>=0?A:B]+=FMath::Abs(Q)*CellM*Dt;};
        for(int32 Y=0;Y<Height;++Y)for(int32 X=0;X<Width-1;++X)
        {
            const int32 E=Y*(Width-1)+X,A=Index(X,Y),B=A+1;
            Qx[E]=Discharge(A,B,Qx[E],CrestX[E],Dt);Accumulate(A,B,Qx[E]);
        }
        for(int32 Y=0;Y<Height-1;++Y)for(int32 X=0;X<Width;++X)
        {
            const int32 E=Y*Width+X,A=Index(X,Y),B=A+Width;
            Qy[E]=Discharge(A,B,Qy[E],CrestY[E],Dt);Accumulate(A,B,Qy[E]);
        }
        for(int32 I=0;I<Depth.Num();++I)
        {
            if(!FMath::IsFinite(Outgoing[I]))return false;
            Limiter[I]=Outgoing[I]>0?FMath::Min(1.,Depth[I]*CellM*CellM/Outgoing[I]):1;
        }
        auto Transfer=[&](int32 A,int32 B,double& Q)
        {
            Q*=Limiter[Q>=0?A:B];
            const double H=Q*Dt/CellM;
            Depth[A]-=H;Depth[B]+=H;
        };
        for(int32 Y=0;Y<Height;++Y)for(int32 X=0;X<Width-1;++X)
        {const int32 A=Index(X,Y);Transfer(A,A+1,Qx[Y*(Width-1)+X]);}
        for(int32 Y=0;Y<Height-1;++Y)for(int32 X=0;X<Width;++X)
        {const int32 A=Index(X,Y);Transfer(A,A+Width,Qy[Y*Width+X]);}
        for(const auto& Pair:Drains)
        {
            const double Removed=FMath::Min(Depth[Pair.Key]*CellM*CellM,Pair.Value*Dt);
            Depth[Pair.Key]-=Removed/(CellM*CellM);DrainedM3+=Removed;
        }
        for(double& H:Depth)
        {
            if(!FMath::IsFinite(H)||H< -1.e-8||H>100)return false;
            if(H<0){NumericalCorrectionM3-=H*CellM*CellM;H=0;}
        }
        EnforceBoundaries();return true;
    }
};
