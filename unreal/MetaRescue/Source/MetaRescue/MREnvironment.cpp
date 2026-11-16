#include "MREnvironment.h"

const TCHAR* MRDisturbanceName(EMRDisturbance Kind)
{
    static const TCHAR* Names[]={TEXT("collapse"),TEXT("fire"),TEXT("flood"),TEXT("mud"),
        TEXT("road_damage"),TEXT("smoke"),TEXT("low_visibility"),TEXT("new_target")};
    return Names[uint8(Kind)];
}
FMRDistrictEnvironment::FMRDistrictEnvironment()
{ for(int32 I=0;I<8;I++)Probabilities[I]=MRDistrictSettings::ProbabilityPct[I]; }
FIntPoint FMRDistrictEnvironment::Cell(const FVector& P)
{ return FIntPoint(FMath::FloorToInt(P.X/MRDistrictSettings::CellCm),FMath::FloorToInt(P.Y/MRDistrictSettings::CellCm)); }
FVector FMRDistrictEnvironment::Center(FIntPoint P)
{ return FVector((P.X+.5)*MRDistrictSettings::CellCm,(P.Y+.5)*MRDistrictSettings::CellCm,4); }
bool FMRDistrictEnvironment::Protected(const FVector& P)
{ return P.X<650&&P.Y<4200; }

void FMRDistrictEnvironment::Generate(const TArray<FMREventSite>& Sites)
{
    Tape.Empty();ResetApplied();
    FRandomStream Rng(Seed+982451653);TSet<FString> Used;int32 Serial=0;
    auto Make=[&](const FMREventSite& Site,double At)
    {
        FMRDisturbance E;E.Id=FString::Printf(TEXT("E%04d"),++Serial);E.Time=At;
        E.Kind=Site.Kind;E.SiteId=Site.Id;E.Source=Site.Position;
        if(Protected(E.Source))E.Rejection=TEXT("protected_base");
        else if(Used.Contains(Site.Id))E.Rejection=TEXT("site_exhausted");
        else
        {
            if(Site.Kind!=EMRDisturbance::Smoke&&Site.Kind!=EMRDisturbance::LowVisibility)Used.Add(Site.Id);
            const int32 Radius=Rng.RandRange(0,2)==2?2:1;
            const FIntPoint Origin=Cell(E.Source);
            for(FIntPoint C:Site.Cells)
                if(FMath::Abs(C.X-Origin.X)<=Radius&&FMath::Abs(C.Y-Origin.Y)<=Radius&&
                   !Protected(Center(C))&&Rng.FRand()<(Radius==1?.84f:.64f))E.Cells.AddUnique(C);
            if(Site.Cells.Contains(Origin)&&!Protected(Center(Origin)))E.Cells.AddUnique(Origin);
            if(E.Kind==EMRDisturbance::NewTarget)E.TargetId=100+Serial;
            else if(E.Cells.IsEmpty())E.Rejection=TEXT("no_eligible_surface");
        }
        return E;
    };
    if(Mode==TEXT("static"))return;
    const bool Showcase=Mode==TEXT("showcase");
    for(double T=MRDistrictSettings::WindowSeconds;T<Horizon;T+=MRDistrictSettings::WindowSeconds)
        for(int32 K=0;K<8;K++)
        {
            const float Draw=Rng.FRand()*100;
            if(Showcase?T>MRDistrictSettings::WindowSeconds:Draw>=Probabilities[K])continue;
            TArray<const FMREventSite*> Candidates;
            for(const auto& Site:Sites)if(uint8(Site.Kind)==K&&!Used.Contains(Site.Id))Candidates.Add(&Site);
            if(Candidates.IsEmpty())
            {
                FMRDisturbance E;E.Id=FString::Printf(TEXT("E%04d"),++Serial);E.Kind=EMRDisturbance(K);
                E.Time=T;E.Rejection=TEXT("no_eligible_site");Tape.Add(E);continue;
            }
            const auto& Site=*Candidates[Showcase?0:Rng.RandRange(0,Candidates.Num()-1)];
            FMRDisturbance E=Make(Site,Showcase?30+K*14:T);Tape.Add(E);
            if(!E.Rejection.IsEmpty()||(K!=1&&K!=2))continue;
            TArray<FIntPoint> Frontier=E.Cells;
            for(int32 Step=1;Step<=2;Step++)
            {
                if(E.Time+Step*30>=Horizon||Frontier.IsEmpty()||Rng.FRand()>.72f)break;
                FMRDisturbance Growth=E;Growth.Id=FString::Printf(TEXT("E%04d"),++Serial);
                Growth.ParentId=E.Id;Growth.bPropagation=true;Growth.Time=E.Time+Step*30;Growth.Cells.Empty();
                // Sample at most three distinct frontier cells, as in v0.3.
                TArray<FIntPoint> Pool=Frontier;
                for(int32 Pick=0;Pick<3&&!Pool.IsEmpty();Pick++)
                {
                    const int32 J=Rng.RandRange(0,Pool.Num()-1);const FIntPoint C=Pool[J];Pool.RemoveAtSwap(J);
                    for(FIntPoint D:{FIntPoint(1,0),FIntPoint(-1,0),FIntPoint(0,1),FIntPoint(0,-1)})
                        if(Rng.FRand()<.65f&&Site.Cells.Contains(C+D)&&!Protected(Center(C+D)))Growth.Cells.AddUnique(C+D);
                }
                if(Growth.Cells.IsEmpty())break;
                Frontier=Growth.Cells;Tape.Add(Growth);
            }
        }
    Tape.Sort([](const auto& A,const auto& B){return A.Time==B.Time?A.Id<B.Id:A.Time<B.Time;});
}

void FMRDistrictEnvironment::ResetApplied()
{
    Applied.Empty();
    AppliedCells.Empty();
    VisibleCells.Empty();
    AppliedIds.Empty();
    SmokeCache.Empty();SmokeCacheTime=-1;SmokeCacheRevision=-1;
    Index=Revision=0;
    Time=0;
}

double FMRDistrictEnvironment::NextBoundary() const
{
    double Next=Tape.IsValidIndex(Index)?Tape[Index].Time:TNumericLimits<double>::Max();
    for(const auto& Event:Applied)
    {
        for(double End:{ActiveUntil(Event),VisibilityUntil(Event)})
            if(End>Time+1.e-9)Next=FMath::Min(Next,End);
    }
    return Next;
}

TArray<FMRDisturbance> FMRDistrictEnvironment::Advance(double NewTime)
{
    TArray<FMRDisturbance> Due;
    if(NewTime<Time)return Due;
    const double Previous=Time;Time=NewTime;
    for(const auto& E:Applied)
    {
        const double Until=ActiveUntil(E),VisibleUntil=VisibilityUntil(E);
        if((Until>=0&&Previous<Until&&Time>=Until)||(VisibleUntil>=0&&Previous<VisibleUntil&&Time>=VisibleUntil))Revision++;
        if(E.Kind==EMRDisturbance::Flood)
        {
            const auto Level=[&](double T){return FMath::FloorToInt(FMath::Min(MRDistrictSettings::MaximumFloodCm,
                float(T-E.Time)*MRDistrictSettings::WaterRiseCmPerSecond));};
            if(Level(Previous)!=Level(Time))Revision++;
        }
    }
    while(Index<Tape.Num()&&Tape[Index].Time<=Time+1.e-9)
    {
        auto E=Tape[Index++];Due.Add(E);
        if(E.Rejection.IsEmpty()){IndexApplied(Applied.Add(E));Revision++;}
    }
    return Due;
}
bool FMRDistrictEnvironment::IsActive(const FMRDisturbance& E) const
{
    if(E.Time>Time+1.e-9)return false;
    const double Until=ActiveUntil(E);return Until<0||Time+1.e-9<Until;
}
double FMRDistrictEnvironment::ActiveUntil(const FMRDisturbance& E) const
{
    if(E.ExpiresAt>=0)return E.ExpiresAt;
    return E.Kind==EMRDisturbance::Smoke?E.Time+MRDistrictSettings::SmokeSeconds:
        E.Kind==EMRDisturbance::LowVisibility?E.Time+MRDistrictSettings::FogSeconds:-1;
}
double FMRDistrictEnvironment::VisibilityUntil(const FMRDisturbance& E) const
{
    if(E.VisibilityExpiresAt>=0)return E.VisibilityExpiresAt;
    return E.Kind==EMRDisturbance::Fire?E.Time+MRDistrictSettings::FireSmokeSeconds:
        E.Kind==EMRDisturbance::Collapse?E.Time+24:ActiveUntil(E);
}
void FMRDistrictEnvironment::IndexApplied(int32 I)
{
    const auto& E=Applied[I];AppliedIds.Add(E.Id,I);
    for(FIntPoint C:E.Cells)
    {
        AppliedCells.FindOrAdd(C).AddUnique(I);VisibleCells.FindOrAdd(C).AddUnique(I);
        if(E.Kind==EMRDisturbance::Fire)
            for(FIntPoint D:{FIntPoint(1,0),FIntPoint(-1,0),FIntPoint(0,1),FIntPoint(0,-1)})VisibleCells.FindOrAdd(C+D).AddUnique(I);
    }
    if(bDetailedHazards&&!E.bPropagation&&(E.Kind==EMRDisturbance::Fire||E.Kind==EMRDisturbance::Smoke||
        E.Kind==EMRDisturbance::Collapse||E.Kind==EMRDisturbance::LowVisibility))
    {
        // Include the full future, wind-leaned plume. Both arrival and clearing
        // remain observable when its visible volume crosses an adjacent street.
        const auto Bounds=SmokeDescriptor(E,3600).Bounds();
        const auto Min=Cell(Bounds.Min),Max=Cell(Bounds.Max);
        for(int32 X=Min.X;X<=Max.X;++X)for(int32 Y=Min.Y;Y<=Max.Y;++Y)
            VisibleCells.FindOrAdd(FIntPoint(X,Y)).AddUnique(I);
    }
}
const FMRDisturbance* FMRDistrictEnvironment::FindApplied(const FString& Id) const
{const int32* I=AppliedIds.Find(Id);return I&&Applied.IsValidIndex(*I)?&Applied[*I]:nullptr;}
bool FMRDistrictEnvironment::HasEffect(EMRDisturbance Kind,const FVector& P) const
{
    if(const auto* Indices=AppliedCells.Find(Cell(P)))
        for(int32 I:*Indices)if(Applied[I].Kind==Kind&&IsActive(Applied[I]))return true;
    return false;
}
float FMRDistrictEnvironment::Depth(const FVector& P) const
{
    float Result=0;const auto C=Cell(P);
    if(const auto* Indices=AppliedCells.Find(C))for(int32 I:*Indices)
    {
        const auto& E=Applied[I];if(E.Kind==EMRDisturbance::Flood&&IsActive(E))
            Result=FMath::Max(Result,FMath::Min(MRDistrictSettings::MaximumFloodCm,float(Time-E.Time)*MRDistrictSettings::WaterRiseCmPerSecond));
    }
    return Result;
}
float FMRDistrictEnvironment::Cost(const FVector& P,bool IncludeWater) const
{
    float Result=1;const auto C=Cell(P);
    if(const auto* Indices=AppliedCells.Find(C))for(int32 I:*Indices)
    {
        const auto& E=Applied[I];if(!IsActive(E))continue;
        if(E.Kind==EMRDisturbance::Mud)Result=FMath::Max(Result,MRDistrictSettings::MudCost);
        if(E.Kind==EMRDisturbance::RoadDamage)Result=FMath::Max(Result,MRDistrictSettings::DamagedRoadCost);
    }
    if(IncludeWater&&Depth(P)>4)Result=FMath::Max(Result,2.f);
    return Result;
}
bool FMRDistrictEnvironment::Unsafe(const FVector& P,bool IncludeWater) const
{
    if(IncludeWater&&Depth(P)>MRDistrictSettings::UnsafeWaterCm)return true;
    const auto C=Cell(P);
    if(const auto* Indices=AppliedCells.Find(C))for(int32 I:*Indices)
    {const auto& E=Applied[I];if(IsActive(E)&&(E.Kind==EMRDisturbance::Fire||E.Kind==EMRDisturbance::Collapse))return true;}
    return false;
}
float FMRDistrictEnvironment::Visibility(const FVector& P) const
{
    if(bDetailedHazards)
    {
        double Density=0;
        for(const auto& Volume:SmokeVolumes())Density+=Volume.Extinction(P);
        // Public surface readings express transmission through ten metres;
        // sensor rays integrate their actual length through the same field.
        return FMath::Exp(-1000*Density);
    }
    bool Smoke=false,Fog=false;const auto C=Cell(P);
    if(const auto* Indices=VisibleCells.Find(C))for(int32 I:*Indices)
    {
        const auto& E=Applied[I];if(!IsActive(E)||P.Z>E.VisibilityTopCm)continue;
        if(E.Kind==EMRDisturbance::LowVisibility&&E.Cells.Contains(C))Fog=true;
        if(E.Kind==EMRDisturbance::Smoke&&E.Cells.Contains(C))Smoke=true;
        if(E.Kind==EMRDisturbance::Collapse&&Time+1.e-9<VisibilityUntil(E)&&E.Cells.Contains(C))Smoke=true;
        if(E.Kind==EMRDisturbance::Fire&&Time+1.e-9<VisibilityUntil(E))Smoke=true;
    }
    return (Smoke?MRDistrictSettings::SmokeQuality:1)*(Fog?MRDistrictSettings::FogQuality:1);
}

FMRSmokeVolume FMRDistrictEnvironment::SmokeDescriptor(const FMRDisturbance& E,double Age) const
{
    FMRSmokeVolume V;V.EventId=E.Id;V.Source=E.Source;V.Source.Z=E.SmokeEmissionHeightCm;
    V.ExtinctionPerCm=.006;
    V.WindCmPerSecond=WindCmPerSecond;V.Strength=FMath::Clamp(Age/4.,0.,1.);
    if(E.Kind==EMRDisturbance::Fire)
    {
        V.RadiusCm=650;V.RadiusGrowth=.28;V.RiseCmPerSecond=280;V.HeightCm=4200;
    }
    else if(E.Kind==EMRDisturbance::Collapse)
    {
        V.RadiusCm=1300;V.RadiusGrowth=.1;V.RiseCmPerSecond=100;V.HeightCm=900;
        V.WindCmPerSecond*=.2;V.ExtinctionPerCm=.0018;
    }
    else if(E.Kind==EMRDisturbance::LowVisibility)
    {
        V.RadiusCm=1800;V.RadiusGrowth=.1;V.RiseCmPerSecond=100;V.HeightCm=2800;
        V.WindCmPerSecond=FVector::ZeroVector;V.ExtinctionPerCm=.0004;
    }
    const double VisibleEnd=VisibilityUntil(E);
    if(VisibleEnd>=0)V.Strength*=FMath::Clamp((VisibleEnd-Time)/10.,0.,1.);
    V.HeightCm=FMath::Max(1.,FMath::Min(V.HeightCm,Age*V.RiseCmPerSecond));
    return V;
}

const TArray<FMRSmokeVolume>& FMRDistrictEnvironment::SmokeVolumes() const
{
    if(SmokeCacheTime==Time&&SmokeCacheRevision==Revision)return SmokeCache;
    SmokeCache.Empty();SmokeCacheTime=Time;SmokeCacheRevision=Revision;
    if(!bDetailedHazards)return SmokeCache;
    for(const auto& E:Applied)
    {
        if(E.bPropagation||Time<=E.Time||
           (VisibilityUntil(E)>=0&&Time>=VisibilityUntil(E))||
           (E.Kind!=EMRDisturbance::Fire&&E.Kind!=EMRDisturbance::Smoke&&
            E.Kind!=EMRDisturbance::Collapse&&E.Kind!=EMRDisturbance::LowVisibility))continue;
        auto Volume=SmokeDescriptor(E,Time-E.Time);
        if(Volume.Strength>0&&Volume.IsValid())SmokeCache.Add(Volume);
    }
    return SmokeCache;
}
