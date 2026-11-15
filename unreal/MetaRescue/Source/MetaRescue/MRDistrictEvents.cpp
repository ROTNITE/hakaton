#include "MRWorld.h"
#include "MRAgent.h"
#include "Components/StaticMeshComponent.h"
#include "Components/PointLightComponent.h"
#include "Components/BoxComponent.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "NiagaraComponent.h"
#include "NiagaraFunctionLibrary.h"
#include "NiagaraSystem.h"
#include "ProceduralMeshComponent.h"
#include "Misc/App.h"
#include "Misc/CommandLine.h"
#include "Misc/Crc.h"
#include "Misc/Parse.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Serialization/JsonSerializer.h"
#include "Dom/JsonObject.h"
#if WITH_DEV_AUTOMATION_TESTS
#include "Misc/AutomationTest.h"
#endif

namespace
{
constexpr float MinimumHazardCullDistanceCm=65000.f;
constexpr float MaximumHazardCullDistanceCm=105000.f;
constexpr int32 MaxFireLights=4;

bool IsEventVeil(FName Kind)
{
    return Kind==TEXT("SmokeVeil")||Kind==TEXT("FogVeil");
}

float HazardCullDistance(int32 GridSize)
{
    return FMath::Clamp(GridSize*3000.f,MinimumHazardCullDistanceCm,MaximumHazardCullDistanceCm);
}

void BuildEventVeilMesh(const TArray<FIntPoint>& Cells,const FVector& Origin,
    TArray<FVector>& Vertices,TArray<int32>& Triangles,TArray<FLinearColor>& Colors)
{
    TSet<FIntPoint> Footprint;
    Footprint.Reserve(Cells.Num());
    for(const FIntPoint& Cell:Cells)Footprint.Add(Cell);
    constexpr double HalfCell=MRDistrictSettings::CellCm/2.;
    constexpr double FeatherCm=155.;
    Vertices.Reserve(Cells.Num()*9);
    Colors.Reserve(Cells.Num()*9);
    Triangles.Reserve(Cells.Num()*24);
    for(const FIntPoint& Cell:Cells)
    {
        const FVector Center=FMRDistrictEnvironment::Center(Cell)-Origin;
        const bool West=!Footprint.Contains(Cell+FIntPoint(-1,0));
        const bool East=!Footprint.Contains(Cell+FIntPoint(1,0));
        const bool South=!Footprint.Contains(Cell+FIntPoint(0,-1));
        const bool North=!Footprint.Contains(Cell+FIntPoint(0,1));
        const int32 Start=Vertices.Num();
        for(int32 Y=-1;Y<=1;++Y)for(int32 X=-1;X<=1;++X)
        {
            const double U=X*HalfCell,V=Y*HalfCell;
            double Edge=FeatherCm;
            if(West)Edge=FMath::Min(Edge,U+HalfCell);
            if(East)Edge=FMath::Min(Edge,HalfCell-U);
            if(South)Edge=FMath::Min(Edge,V+HalfCell);
            if(North)Edge=FMath::Min(Edge,HalfCell-V);
            if(X!=0&&Y!=0&&!Footprint.Contains(Cell+FIntPoint(X,Y)))Edge=0.;
            Vertices.Emplace(Center.X+U,Center.Y+V,0.);
            Colors.Emplace(0.f,float(Edge/FeatherCm),0.f,1.f);
        }
        for(int32 Y=0;Y<2;++Y)for(int32 X=0;X<2;++X)
        {
            const int32 A=Start+Y*3+X;
            Triangles.Append({A,A+4,A+1,A,A+3,A+4});
        }
    }
}
constexpr const TCHAR* FabFracture=TEXT("/Game/EffectsV3/Revision3/Fab/M_EventFracture.M_EventFracture");
constexpr const TCHAR* FabDebris=TEXT("/Game/EffectsV3/Revision3/Fab/SM_EventBurntDebris.SM_EventBurntDebris");

UMaterialInterface* EventSurfaceMaterial(const TCHAR* Name,bool bUseOptionalArt)
{
    if(bUseOptionalArt&&FCString::Strcmp(Name,TEXT("M_EventFlood"))==0)
        if(auto* Material=LoadObject<UMaterialInterface>(nullptr,
            TEXT("/Game/EffectsV3/Revision4/M_EventFlood.M_EventFlood"),nullptr,LOAD_NoWarn|LOAD_Quiet))
            return Material;
    if(bUseOptionalArt&&FCString::Strcmp(Name,TEXT("M_EventFracture"))==0)
        if(auto* Material=LoadObject<UMaterialInterface>(nullptr,FabFracture,nullptr,LOAD_NoWarn|LOAD_Quiet))
            return Material;
    if(bUseOptionalArt&&(FCString::Strcmp(Name,TEXT("M_EventFlood"))==0||FCString::Strcmp(Name,TEXT("M_EventFoam"))==0))
    {
        const FString Path=FString::Printf(TEXT("/Game/EffectsV3/Revision3/%s.%s"),Name,Name);
        if(auto* Material=LoadObject<UMaterialInterface>(nullptr,*Path,nullptr,LOAD_NoWarn|LOAD_Quiet))
            return Material;
    }
    const FString Path=FString::Printf(TEXT("/Game/EffectsV3/Revision2/%s.%s"),Name,Name);
    return MRSceneMaterial(LoadObject<UMaterialInterface>(nullptr,*Path));
}

double HazardVisualEnd(const FMRDistrictEnvironment& Environment,const FMRDisturbance& Event,FName Kind)
{
    const double EffectEnd=Environment.ActiveUntil(Event);
    if(Kind==TEXT("HeavySmoke")||Kind==TEXT("LowVisibility")||Kind==TEXT("CollapseDust")||IsEventVeil(Kind))
    {
        const double VisibilityEnd=Environment.VisibilityUntil(Event);
        if(EffectEnd>=0&&VisibilityEnd>=0)return FMath::Min(EffectEnd,VisibilityEnd);
        return VisibilityEnd>=0?VisibilityEnd:EffectEnd;
    }
    if(Kind==TEXT("TargetArrival"))return Event.Time+4.;
    if(Kind==TEXT("ElectricalIgnition"))
        return EffectEnd>=0?FMath::Min(EffectEnd,Event.Time+.8):Event.Time+.8;
    if(Kind==TEXT("BuildingFire")||Kind==TEXT("Sparks")||Kind==TEXT("FireLight")||Kind==TEXT("PipeLeak"))
        return EffectEnd;
    return -1.;
}
}

void AMRWorld::InitializeEnvironment()
{
    Environment.Seed=Seed;
    FString Mode;if(FParse::Value(FCommandLine::Get(),TEXT("MREnvironment="),Mode))Environment.Mode=Mode;
    FParse::Value(FCommandLine::Get(),TEXT("MRSeed="),Environment.Seed);
    FParse::Value(FCommandLine::Get(),TEXT("MRHorizon="),Environment.Horizon);
    if(Environment.Mode!=TEXT("random")&&Environment.Mode!=TEXT("static")&&Environment.Mode!=TEXT("showcase"))
    {UE_LOG(LogTemp,Error,TEXT("MR invalid environment mode"));FGenericPlatformMisc::RequestExit(false);return;}
    for(int32 K=0;K<8;K++)
    {
        const FString Key=FString::Printf(TEXT("MRProbability_%s="),MRDisturbanceName(EMRDisturbance(K)));
        FParse::Value(FCommandLine::Get(),*Key,Environment.Probabilities[K]);
        if(!FMath::IsFinite(Environment.Probabilities[K])||Environment.Probabilities[K]<0||Environment.Probabilities[K]>100)
        {UE_LOG(LogTemp,Error,TEXT("MR probability outside [0,100]"));FGenericPlatformMisc::RequestExit(false);return;}
    }
    if(FParse::Param(FCommandLine::Get(),TEXT("MRExternalControl")))bDemoDispatcherEnabled=false;
    auto Add=[&](EMRDisturbance Kind,const FString& Id,FVector P)
    {
        FMREventSite Site;Site.Kind=Kind;Site.Id=Id;Site.Position=P;
        if(Kind==EMRDisturbance::Fire)
        {
            FHitResult Support;
            if(GetWorld()->LineTraceSingleByChannel(Support,P+FVector(0,0,180),P-FVector(0,0,800),ECC_Visibility))
                Site.Position.Z=Support.ImpactPoint.Z+5;
        }
        const auto Origin=FMRDistrictEnvironment::Cell(P);
        for(int32 X=-3;X<=3;X++)for(int32 Y=-3;Y<=3;Y++)
        {
            const FIntPoint C=Origin+FIntPoint(X,Y);const FVector At=FMRDistrictEnvironment::Center(C);
            if(FMRDistrictEnvironment::Protected(At))continue;
            bool Inside=false;
            if(Kind!=EMRDisturbance::Smoke&&Kind!=EMRDisturbance::LowVisibility)
                for(const auto& Box:StructureFootprints)if(Box.IsInsideXY(At)){Inside=true;break;}
            if(At.X>11880&&At.X<13820&&At.Y>11880&&At.Y<14120)Inside=true;
            if(!Inside)Site.Cells.Add(C);
        }
        EventSites.Add(Site);
    };
    Add(EMRDisturbance::Collapse,TEXT("unstable_bay"),FVector(7800,6500,24));
    const FVector Fires[]={FVector(10900,7950,80),FVector(6650,10650,24),FVector(2150,6150,24),
        FVector(11800,9350,24),FVector(8900,2500,24),FVector(3300,12790,24)};
    for(int32 I=0;I<6;I++)Add(EMRDisturbance::Fire,FString::Printf(TEXT("fire_%d"),I),Fires[I]);
    const FVector Water[]={FVector(14500,12800,4),FVector(5500,11800,4),FVector(10000,11800,4),
        FVector(14500,8300,4),FVector(10000,3500,4),FVector(5500,6800,4)};
    for(int32 I=0;I<6;I++)Add(EMRDisturbance::Flood,FString::Printf(TEXT("water_%d"),I),Water[I]);
    for(int32 K=3;K<=6;K++)for(int32 I=0;I<12;I++)
    {
        const FVector P(I%2?5500:10000,2300+(I/2)*2000,4);
        Add(EMRDisturbance(K),FString::Printf(TEXT("surface_%d_%d"),K,I),P);
    }
    const FVector Late[]={FVector(10530,3400,24),FVector(6040,2300,24),FVector(6040,6800,24),
        FVector(10530,7600,24),FVector(10530,11400,24),FVector(6040,12200,24),
        FVector(1420,7600,24),FVector(1420,11800,24),FVector(14950,6600,24),
        FVector(14950,9700,24),FVector(8300,10520,24),FVector(3500,10520,24),
        FVector(7700,1420,24),FVector(8800,1420,24),FVector(12000,1420,24)};
    for(int32 I=0;I<15;I++)Add(EMRDisturbance::NewTarget,FString::Printf(TEXT("latent_%d"),I),Late[I]);
    Environment.Generate(EventSites);
    // Latent people are part of simulator truth from reset, hidden until their
    // event and then still unknown to the dispatcher until a real observation.
    for(const auto& E:Environment.Tape)if(E.Kind==EMRDisturbance::NewTarget&&E.Rejection.IsEmpty())
    {
        FMRTarget T;T.Id=E.TargetId;T.Position=E.Source;T.AvailableAt=E.Time;
        auto* Visual=GetWorld()->SpawnActor<AActor>(T.Position,FRotator::ZeroRotator);
        auto* Root=NewObject<USceneComponent>(Visual);Visual->AddInstanceComponent(Root);Visual->SetRootComponent(Root);Root->RegisterComponent();
        Visual->SetActorLocation(T.Position);TArray<FMRAssemblyPart> Parts;
        MRBuildAssembly(Visual,Root,TEXT("Casualty"),FVector::ZeroVector,FRotator::ZeroRotator,FVector::OneVector,false,true,Parts);
        Visual->SetActorHiddenInGame(true);T.Visual=Visual;
        EventTargetIndices.Add(E.Id,Targets.Add(T));
    }
    ExportEnvironmentManifest();
}

void AMRWorld::RecordEnvironmentEvent(const FMRDisturbance& E)
{
    auto J=MakeShared<FJsonObject>();J->SetStringField(TEXT("type"),E.Rejection.IsEmpty()?TEXT("environment_event"):TEXT("environment_attempt_rejected"));
    J->SetStringField(TEXT("event_id"),E.Id);J->SetStringField(TEXT("event_type"),MRDisturbanceName(E.Kind));
    J->SetNumberField(TEXT("time_s"),E.Time);J->SetStringField(TEXT("source"),E.bPropagation?TEXT("propagation"):TEXT("seeded_environment"));
    J->SetStringField(TEXT("parent_id"),E.ParentId);J->SetStringField(TEXT("site_id"),E.SiteId);
    J->SetStringField(TEXT("reason"),E.Rejection);J->SetNumberField(TEXT("world_revision"),Environment.Revision);
    TArray<TSharedPtr<FJsonValue>> Cells;
    for(auto C:E.Cells){TArray<TSharedPtr<FJsonValue>> XY;XY.Add(MakeShared<FJsonValueNumber>(C.X));XY.Add(MakeShared<FJsonValueNumber>(C.Y));Cells.Add(MakeShared<FJsonValueArray>(XY));}
    J->SetArrayField(TEXT("cells"),Cells);
    FString Text;FJsonSerializer::Serialize(J,TJsonWriterFactory<TCHAR,TCondensedJsonPrintPolicy<TCHAR>>::Create(&Text));
    FFileHelper::SaveStringToFile(Text+TEXT("\n"),*(FPaths::ProjectSavedDir()/TEXT("Telemetry/events.jsonl")),FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM,&IFileManager::Get(),FILEWRITE_Append);
}

void AMRWorld::ApplyDisturbance(const FMRDisturbance& E)
{
    if(VisualProbe==TEXT("events")&&!E.bPropagation&&!InspectedEventKinds.Contains(int32(E.Kind)))
    {
        InspectedEventKinds.Add(int32(E.Kind));
        for(float Delay:{2.f,12.f,60.f})
        {
            FMRInspection View;View.Time=E.Time+Delay;
            View.Focus=E.Source+FVector(0,0,E.Kind==EMRDisturbance::Smoke?500:100);
            View.Distance=E.Kind==EMRDisturbance::Collapse?3600:E.Kind==EMRDisturbance::NewTarget?1500:3000;
            View.Name=FString::Printf(TEXT("event-%s-%s-age%d"),*E.Id,MRDisturbanceName(E.Kind),int32(Delay));
            EventInspections.Add(View);
        }
        EventInspections.Sort([](const auto& A,const auto& B){return A.Time<B.Time;});
    }
    auto VFX=[&](const FString& Name,FVector P,FVector Scale,FName EffectRole=NAME_None)
    {
        const TCHAR* Revision=TEXT("Revision2");
        UNiagaraSystem* System=nullptr;
        if(FApp::CanEverRender()&&(Name==TEXT("BuildingFire")||Name==TEXT("HeavySmoke")||Name==TEXT("LowVisibility")))
        {
            const FString Path=FString::Printf(TEXT("/Game/EffectsV3/Revision3/NS_%s.NS_%s"),*Name,*Name);
            System=LoadObject<UNiagaraSystem>(nullptr,*Path,nullptr,LOAD_NoWarn|LOAD_Quiet);
            if(System)Revision=TEXT("Revision3");
        }
        if(!System)
            System=LoadObject<UNiagaraSystem>(nullptr,*FString::Printf(TEXT("/Game/EffectsV3/Revision2/NS_%s.NS_%s"),*Name,*Name));
        if(!System){UE_LOG(LogTemp,Error,TEXT("MR missing v3 effect %s"),*Name);return (UNiagaraComponent*)nullptr;}
        auto* C=UNiagaraFunctionLibrary::SpawnSystemAtLocation(this,System,P,FRotator::ZeroRotator,Scale,false);
        if(C)
        {
            C->ComponentTags={FName(*E.Id),EffectRole.IsNone()?FName(*Name):EffectRole};
            // Cover the standard and 350 m overview, then cull distant sprite detail on larger maps.
            C->SetCullDistance(HazardCullDistance(GridSize));
            HazardVisuals.Add(C);
            if(auto* Material=LoadObject<UMaterialInterface>(nullptr,*FString::Printf(TEXT("/Game/EffectsV3/%s/M_%s.M_%s"),Revision,*Name,*Name)))
            {
                auto* Dynamic=UMaterialInstanceDynamic::Create(Material,C);C->SetVariableMaterial(TEXT("User.EffectMaterial"),Dynamic);
            }
        }
        return C;
    };
    if(E.Kind==EMRDisturbance::Collapse)
    {
        if(!bCoreControlled)ReleaseCollapse();
        DustEffect=VFX(TEXT("CollapseDust"),E.Source+FVector(0,0,120),FVector(5.2,5.2,3.6));
        const FIntPoint Origin=FMRDistrictEnvironment::Cell(E.Source);
        for(const FIntPoint& Cell:E.Cells)
            if(FMath::Abs(Cell.X-Origin.X)+FMath::Abs(Cell.Y-Origin.Y)<=1)
                BuildHazardSurface(E,Cell,2);
    }
    else if(E.Kind==EMRDisturbance::Fire)
    {
        FVector Source=E.Source;
        if(E.bPropagation&&!E.Cells.IsEmpty())
        {
            Source=FMRDistrictEnvironment::Center(E.Cells[0]);FHitResult Ground;
            if(GetWorld()->LineTraceSingleByChannel(Ground,Source+FVector(0,0,300),Source-FVector(0,0,500),ECC_Visibility))
                Source.Z=Ground.ImpactPoint.Z+6;
        }
        FireEffect=VFX(TEXT("BuildingFire"),Source,FVector(4.2,4.2,4.2));
        VFX(TEXT("HeavySmoke"),Source+FVector(0,0,140),FVector(5.4,4.8,4));
        VFX(TEXT("Sparks"),Source+FVector(0,0,60),FVector(.9));
        // The authored legacy site fire_0 is the electrical cabinet.
        if(!bCoreControlled&&!E.bPropagation&&E.SiteId==TEXT("fire_0"))
            VFX(TEXT("IgnitionFlash"),Source+FVector(0,0,70),FVector::OneVector,TEXT("ElectricalIgnition"));
        FHitResult Soot;FCollisionQueryParams SootParams(SCENE_QUERY_STAT(MRScorchSupport),false);
        bool HasGround=GetWorld()->LineTraceSingleByChannel(Soot,Source+FVector(0,0,50),Source-FVector(0,0,800),ECC_Visibility,SootParams);
        if(HasGround&&Soot.ImpactPoint.Z>60)
        {
            // Flame can start on top of a cabinet; a five-metre scorch mark
            // belongs to the ground, not a floating extension of its lid.
            SootParams.AddIgnoredComponent(Soot.GetComponent());
            HasGround=GetWorld()->LineTraceSingleByChannel(Soot,Source+FVector(0,0,50),Source-FVector(0,0,800),ECC_Visibility,SootParams);
        }
        if(HasGround&&Soot.ImpactNormal.Z>.8&&Soot.ImpactPoint.Z>=-100&&Soot.ImpactPoint.Z<=60)
        {
            auto* C=Shape(TEXT("Plane"),Soot.ImpactPoint+FVector(0,0,.8),FVector(500,500,100),TEXT("M_V3Soot"),FRotator::ZeroRotator,false);
            C->ComponentTags={FName(*E.Id),TEXT("Scorch")};HazardVisuals.Add(C);
            if(!E.bPropagation&&FApp::CanEverRender())
                if(auto* Mesh=LoadObject<UStaticMesh>(nullptr,FabDebris,nullptr,LOAD_NoWarn|LOAD_Quiet))
                {
                    const FVector Offsets[]={FVector(55,35,0),FVector(75,-42,0),FVector(105,8,0)};
                    const float Scales[]={1.f,1.38f,1.78f};
                    const uint32 VisualSeed=FCrc::StrCrc32(*E.Id);
                    for(int32 Part=0;Part<int32(UE_ARRAY_COUNT(Offsets));++Part)
                    {
                        const FVector Spot=Soot.ImpactPoint+Offsets[Part];
                        FHitResult Support;
                        if(!GetWorld()->LineTraceSingleByChannel(Support,Spot+FVector(0,0,35),Spot-FVector(0,0,25),
                            ECC_Visibility,SootParams)||Support.ImpactNormal.Z<=.95||
                            FMath::Abs(Support.ImpactPoint.Z-Soot.ImpactPoint.Z)>=12)continue;
                        auto* Debris=NewObject<UStaticMeshComponent>(this);
                        AddInstanceComponent(Debris);
                        Debris->SetupAttachment(GetRootComponent());
                        Debris->SetMobility(EComponentMobility::Movable);
                        Debris->SetStaticMesh(Mesh);
                        Debris->SetCollisionEnabled(ECollisionEnabled::NoCollision);
                        Debris->SetGenerateOverlapEvents(false);
                        Debris->SetCanEverAffectNavigation(false);
                        const float Yaw=float((VisualSeed+93u*Part)%360);
                        Debris->SetWorldLocationAndRotation(Support.ImpactPoint+FVector(0,0,.4),FRotator(0,Yaw,0));
                        Debris->SetWorldScale3D(FVector(Scales[Part]));
                        Debris->ComponentTags={FName(*E.Id),TEXT("BurntDebris")};
                        Debris->RegisterComponent();
                        HazardVisuals.Add(Debris);
                    }
                }
        }
        int32 Lights=0;
        for(const auto& Visual:HazardVisuals)if(Visual&&Visual->ComponentHasTag(TEXT("FireLight")))++Lights;
        if(Lights<MaxFireLights)
        {
            auto* Lamp=NewObject<UPointLightComponent>(this);AddInstanceComponent(Lamp);Lamp->SetupAttachment(GetRootComponent());
            Lamp->SetMobility(EComponentMobility::Movable);Lamp->SetRelativeLocation(Source+FVector(0,0,140));
            Lamp->SetIntensity(22000);Lamp->SetLightColor(FLinearColor(1,.16,.015));Lamp->SetAttenuationRadius(1800);
            Lamp->SetCastShadows(false);Lamp->RegisterComponent();Lamp->ComponentTags={FName(*E.Id),TEXT("FireLight")};HazardVisuals.Add(Lamp);
        }
    }
    else if(E.Kind==EMRDisturbance::Smoke||E.Kind==EMRDisturbance::LowVisibility)
    {
        const bool Smoke=E.Kind==EMRDisturbance::Smoke;
        if(Smoke)VFX(TEXT("HeavySmoke"),E.Source+FVector(0,0,90),FVector(6.3,5.7,4.5));
        else VFX(TEXT("LowVisibility"),E.Source+FVector(0,0,170),FVector(6.4,6.4,3.2));

        if(FApp::CanEverRender()&&!E.Cells.IsEmpty())
        {
            const TCHAR* Path=Smoke?TEXT("/Game/EffectsV3/Revision4/M_EventSmokeVeil.M_EventSmokeVeil"):
                TEXT("/Game/EffectsV3/Revision4/M_EventFogVeil.M_EventFogVeil");
            if(auto* Material=LoadObject<UMaterialInterface>(nullptr,Path,nullptr,LOAD_NoWarn|LOAD_Quiet))
            {
                const FVector Pivot=E.Source+FVector(0,0,Smoke?380:240);
                TArray<FVector> Vertices;
                TArray<int32> Triangles;
                TArray<FLinearColor> Colors;
                BuildEventVeilMesh(E.Cells,Pivot,Vertices,Triangles,Colors);
                auto* Veil=NewObject<UProceduralMeshComponent>(this);
                AddInstanceComponent(Veil);
                Veil->SetupAttachment(GetRootComponent());
                Veil->SetMobility(EComponentMobility::Movable);
                Veil->SetWorldLocation(Pivot);
                Veil->SetCollisionEnabled(ECollisionEnabled::NoCollision);
                Veil->SetGenerateOverlapEvents(false);
                Veil->SetCanEverAffectNavigation(false);
                Veil->SetCastShadow(false);
                Veil->SetCullDistance(HazardCullDistance(GridSize));
                Veil->SetTranslucentSortPriority(Smoke?2:1);
                Veil->ComponentTags={FName(*E.Id),Smoke?FName(TEXT("SmokeVeil")):FName(TEXT("FogVeil"))};
                auto* Dynamic=UMaterialInstanceDynamic::Create(Material,Veil);
                Dynamic->SetScalarParameterValue(TEXT("Fade"),0.f);
                Veil->SetMaterial(0,Dynamic);
                Veil->RegisterComponent();
                Veil->CreateMeshSection_LinearColor(0,Vertices,Triangles,{}, {},Colors,{},false);
                HazardVisuals.Add(Veil);
            }
        }
    }
    else if(E.Kind==EMRDisturbance::NewTarget)
    {
        if(auto* I=EventTargetIndices.Find(E.Id))
        {
            auto& T=Targets[*I];if(T.Visual)T.Visual->SetActorHiddenInGame(false);
            if(!bCoreControlled)
            {
                VFX(TEXT("CollapseDust"),E.Source+FVector(0,0,30),FVector(.7),TEXT("TargetArrival"));
                AppendEvent(TEXT("coarse_target_signal")); // no precise target coordinate in public event
            }
        }
    }
    if(E.Kind==EMRDisturbance::Flood)
    {
        GroundedAssembly(TEXT("Manhole"),E.Source,FRotator::ZeroRotator,FVector::OneVector,TEXT(""));
        LeakEffect=VFX(TEXT("PipeLeak"),E.Source+FVector(0,0,35),FVector(1.2,1.2,1.05));
    }
    if(E.Kind==EMRDisturbance::Flood||E.Kind==EMRDisturbance::Mud||E.Kind==EMRDisturbance::RoadDamage)
        for(const auto Cell:E.Cells)
        {
            const FVector P=FMRDistrictEnvironment::Center(Cell);
            BuildHazardSurface(E,Cell,E.Kind==EMRDisturbance::Flood?0:E.Kind==EMRDisturbance::Mud?1:2);
            if(E.Kind==EMRDisturbance::RoadDamage)
            {
                // Real displaced edge fragments are passable; this event does
                // not create the deep, separately authored sinkhole.
                FRandomStream R(GetTypeHash(Cell)^Environment.Seed);
                for(int32 I=0;I<3;I++)
                {
                    GroundedChunk(R,P+FVector(R.FRandRange(-170,170),R.FRandRange(-170,170),4),FVector(60,45,8));
                    if(auto* Piece=Cast<UProceduralMeshComponent>(Generated.Last()))
                        Piece->SetMaterial(0,MRSceneMaterial(LoadObject<UMaterialInterface>(nullptr,TEXT("/Game/Materials/M_QuarterAsphalt.M_QuarterAsphalt"))));
                }
            }
        }
}

void AMRWorld::BuildHazardSurface(const FMRDisturbance& E,FIntPoint Cell,int32 Layer)
{
    if(SurfaceCells[Layer].Contains(Cell))return;
    SurfaceCells[Layer].Add(Cell);
    const FVector Origin=FMRDistrictEnvironment::Center(Cell);
    TArray<FVector> V,N,FV,FN,WV,WN;TArray<int32> T,FT,WT;TArray<FVector2D> UV,FUV,WUV;
    TArray<FLinearColor> SurfaceColors;
    const bool EdgeWest=!E.Cells.Contains(Cell+FIntPoint(-1,0));
    const bool EdgeEast=!E.Cells.Contains(Cell+FIntPoint(1,0));
    const bool EdgeSouth=!E.Cells.Contains(Cell+FIntPoint(0,-1));
    const bool EdgeNorth=!E.Cells.Contains(Cell+FIntPoint(0,1));
    auto Quad=[&](TArray<FVector>& Vertices,TArray<FVector>& Normals,TArray<int32>& Triangles,
        TArray<FVector2D>& Tex,FVector P,FVector Size,float Ground=0.f,TArray<FLinearColor>* Colors=nullptr)
    {
        const int32 I=Vertices.Num();
        for(FVector Offset:{FVector(-.5,-.5,0),FVector(.5,-.5,0),FVector(.5,.5,0),FVector(-.5,.5,0)})
        {
            const FVector Corner=P+Offset*Size;
            Vertices.Add(Corner);Normals.Add(FVector::UpVector);Tex.Add(FVector2D(Offset.X+.5,Offset.Y+.5));
            if(Colors)
            {
                double EdgeCm=75.;
                if(EdgeWest)EdgeCm=FMath::Min(EdgeCm,250.+Corner.X);
                if(EdgeEast)EdgeCm=FMath::Min(EdgeCm,250.-Corner.X);
                if(EdgeSouth)EdgeCm=FMath::Min(EdgeCm,250.+Corner.Y);
                if(EdgeNorth)EdgeCm=FMath::Min(EdgeCm,250.-Corner.Y);
                // Both inputs describe existing support and footprint. They feed only the shader.
                Colors->Emplace((Ground+100.f)/155.f,float(FMath::Clamp(EdgeCm/75.,0.,1.)),0.f,1.f);
            }
        }
        Triangles.Append({I,I+2,I+1,I,I+3,I+2});
    };
    auto InBuilding=[&](FVector P)
    {for(const auto& Box:StructureFootprints)if(Box.ExpandBy(36).IsInsideXY(P))return true;return false;};
    FCollisionQueryParams Params(SCENE_QUERY_STAT(MRSurfaceHeight),false);
    for(AMRAgent* A:Agents)Params.AddIgnoredActor(A);
    // Half-metre samples conform to the actual low ground. Tall props and roofs
    // are excluded; clipped cells never create water through a facade.
    for(int32 X=0;X<10;X++)for(int32 Y=0;Y<10;Y++)
    {
        const FVector P(Cell.X*500+X*50+25,Cell.Y*500+Y*50+25,0);
        if(InBuilding(P))continue;
        FHitResult Hit;
        if(!GetWorld()->LineTraceSingleByChannel(Hit,P+FVector(0,0,60),P-FVector(0,0,400),ECC_Visibility,Params)||
            Hit.ImpactNormal.Z<.8||Hit.ImpactPoint.Z>55||Hit.ImpactPoint.Z<-100)continue;
        const float Ground=Hit.ImpactPoint.Z;
        FVector Local=P-Origin;Local.Z=Layer==0?0:Ground-Origin.Z+1+Layer*.2;
        Quad(V,N,T,UV,Local,FVector(50,50,0),Ground,&SurfaceColors);
        if(Layer!=0)continue;
        FloodGroundHeights.Add(FIntPoint(FMath::FloorToInt(P.X/50),FMath::FloorToInt(P.Y/50)),Ground);
        for(FVector D:{FVector(1,0,0),FVector(-1,0,0),FVector(0,1,0),FVector(0,-1,0)})
        {
            const FVector Q=P+D*50;
            const bool Wall=InBuilding(Q);
            const bool Rim=!E.Cells.Contains(FMRDistrictEnvironment::Cell(Q));
            if(!Wall&&!Rim)continue;
            FVector Edge=Local+D*20;Edge.Z=1;
            const FVector Size=FMath::Abs(D.X)>.5?FVector(15,50,0):FVector(50,15,0);
            Quad(FV,FN,FT,FUV,Edge,Size*FVector(1.6,1.6,1));
            Edge.Z=Ground-Origin.Z+.35;Quad(WV,WN,WT,WUV,Edge,Size*FVector(3.6,3.6,1));
        }
    }
    auto Mesh=[&](const TCHAR* Material,TArray<FVector>& Vertices,TArray<FVector>& Normals,
        TArray<int32>& Triangles,TArray<FVector2D>& Tex,const TArray<FLinearColor>& Colors,bool Floating)
    {
        if(Vertices.IsEmpty())return;
        auto* C=NewObject<UProceduralMeshComponent>(this);AddInstanceComponent(C);C->SetupAttachment(GetRootComponent());
        C->SetMobility(EComponentMobility::Movable);C->SetRelativeLocation(Origin);
        C->SetCollisionEnabled(ECollisionEnabled::NoCollision);C->SetCastShadow(false);
        C->RegisterComponent();C->CreateMeshSection_LinearColor(0,Vertices,Triangles,Normals,Tex,Colors,{},false);
        C->SetMaterial(0,EventSurfaceMaterial(Material,FApp::CanEverRender()));
        const TCHAR* RoleName=Floating?TEXT("flood"):Layer==2?TEXT("fractured_surface"):MRDisturbanceName(E.Kind);
        C->ComponentTags={FName(*E.Id),FName(RoleName)};
        // A fixed wet rim follows the ground, rather than rising with the water.
        if(!Floating&&Layer==0)C->ComponentTags[1]=TEXT("wet_rim");
        HazardVisuals.Add(C);
    };
    Mesh(Layer==0?TEXT("M_EventFlood"):Layer==1?TEXT("M_EventMud"):TEXT("M_EventFracture"),
        V,N,T,UV,SurfaceColors,Layer==0);
    Mesh(TEXT("M_EventFoam"),FV,FN,FT,FUV,{},true);
    Mesh(TEXT("M_EventWetEdge"),WV,WN,WT,WUV,{},false);
}

void AMRWorld::TickHazardVisuals(float Dt)
{
    for(int32 Index=HazardVisuals.Num()-1;Index>=0;--Index)
    {
        USceneComponent* C=HazardVisuals[Index];
        if(!C||C->ComponentTags.Num()<2)continue;
        const FName Kind=C->ComponentTags[1];
        const auto* E=Environment.FindApplied(C->ComponentTags[0].ToString());
        if(!E)continue;
        const double End=HazardVisualEnd(Environment,*E,Kind);
        if(End>=0&&Environment.Time+1.e-9>=End)
        {
            if(DustEffect.Get()==C)DustEffect=nullptr;
            if(FireEffect.Get()==C)FireEffect=nullptr;
            if(LeakEffect.Get()==C)LeakEffect=nullptr;
            CoreEventComponents.RemoveSingleSwap(HazardVisuals[Index],EAllowShrinking::No);
            HazardVisuals.RemoveAtSwap(Index,1,EAllowShrinking::No);
            C->DestroyComponent();
            continue;
        }
        const float Age=float(Environment.Time-E->Time);
        if(Kind==TEXT("flood"))
        {
            FVector P=C->GetComponentLocation();
            const float Depth=Environment.Depth(P);
            P.Z=4+Depth;
            C->SetWorldLocation(P);
            C->SetVisibility(Depth>0);
        }
        if(Kind==TEXT("wet_rim"))C->SetVisibility(Environment.Depth(C->GetComponentLocation())>0);
        if(Kind==TEXT("mud"))C->SetVisibility(Environment.HasEffect(EMRDisturbance::Mud,C->GetComponentLocation()));
        if(Kind==TEXT("fractured_surface"))
        {
            const FVector P=C->GetComponentLocation();
            C->SetVisibility(Environment.HasEffect(EMRDisturbance::RoadDamage,P)||Environment.HasEffect(EMRDisturbance::Collapse,P));
        }
        if(auto* Light=Cast<UPointLightComponent>(C))Light->SetIntensity(22000*(.85+.12*FMath::Sin(Age*11)+.08*FMath::Sin(Age*17)));
        auto* FX=Cast<UNiagaraComponent>(C);
        if(FX||IsEventVeil(Kind))
        {
            const float Duration=End>=0?float(End-E->Time):0.f;
            const float FadeOutSeconds=FMath::Min(4.f,Duration*.25f);
            const float FadeInSeconds=Kind==TEXT("ElectricalIgnition")?.08f:1.5f;
            const float Fade=FMath::SmoothStep(0.f,FadeInSeconds,Age)*(Duration>0?
                1-FMath::SmoothStep(Duration-FadeOutSeconds,Duration,Age):1.f);
            if(FX)
            {
                TArray<UMaterialInterface*> Materials;
                FX->GetUsedMaterials(Materials);
                for(auto* Material:Materials)if(auto* Dynamic=Cast<UMaterialInstanceDynamic>(Material))
                    Dynamic->SetScalarParameterValue(TEXT("Fade"),Fade);
            }
            else if(auto* Veil=Cast<UProceduralMeshComponent>(C))
                if(auto* Dynamic=Cast<UMaterialInstanceDynamic>(Veil->GetMaterial(0)))
                    Dynamic->SetScalarParameterValue(TEXT("Fade"),Fade);
        }
    }
}

#if WITH_DEV_AUTOMATION_TESTS
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMRHazardVisualExpiry,"MetaRescue.Environment.HazardVisualExpiry",
    EAutomationTestFlags::EditorContext|EAutomationTestFlags::EngineFilter)
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMREventVeilFootprint,"MetaRescue.Environment.EventVeilFootprint",
    EAutomationTestFlags::EditorContext|EAutomationTestFlags::EngineFilter)
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMRFabEffectFallback,"MetaRescue.Environment.FabEffectFallback",
    EAutomationTestFlags::EditorContext|EAutomationTestFlags::EngineFilter)
bool FMREventVeilFootprint::RunTest(const FString& Parameters)
{
    TArray<FVector> Vertices;
    TArray<int32> Triangles;
    TArray<FLinearColor> Colors;
    const TArray<FIntPoint> Cells={FIntPoint(0,0),FIntPoint(1,0)};
    BuildEventVeilMesh(Cells,FVector::ZeroVector,Vertices,Triangles,Colors);
    if(!TestEqual(TEXT("nine vertices per visual cell"),Vertices.Num(),18)||
       !TestEqual(TEXT("one weight per vertex"),Colors.Num(),18))return false;
    TestEqual(TEXT("eight triangles per visual cell"),Triangles.Num(),48);
    TestTrue(TEXT("only declared cells are covered"),Vertices.Contains(FVector(0,0,0))&&
        Vertices.Contains(FVector(1000,500,0))&&Vertices.Contains(FVector(500,250,0)));
    TestEqual(TEXT("outer edge is transparent"),Colors[3].G,0.f);
    TestEqual(TEXT("shared edge remains opaque before material fade"),Colors[5].G,1.f);
    TestEqual(TEXT("both copies agree at shared edge"),Colors[12].G,Colors[5].G);
    Vertices.Reset();Triangles.Reset();Colors.Reset();
    BuildEventVeilMesh({FIntPoint(0,0),FIntPoint(1,0),FIntPoint(0,1)},FVector::ZeroVector,
        Vertices,Triangles,Colors);
    TestEqual(TEXT("inside corner still fades into missing diagonal"),Colors[8].G,0.f);
    TestEqual(TEXT("inside corner has no duplicated sharp vertex"),Colors[15].G,0.f);
    return true;
}

bool FMRFabEffectFallback::RunTest(const FString& Parameters)
{
    auto* Fallback=EventSurfaceMaterial(TEXT("M_EventFracture"),false);
    if(!TestNotNull(TEXT("procedural fracture fallback exists"),Fallback))return false;
    TestTrue(TEXT("fallback stays in the procedural revision"),
        Fallback->GetPathName().StartsWith(TEXT("/Game/EffectsV3/Revision2/")));
    auto* Optional=LoadObject<UMaterialInterface>(nullptr,FabFracture,nullptr,LOAD_NoWarn|LOAD_Quiet);
    TestTrue(TEXT("rendering resolves the optional Fab material or the procedural fallback"),
        EventSurfaceMaterial(TEXT("M_EventFracture"),true)==(Optional?Optional:Fallback));
    return true;
}

bool FMRHazardVisualExpiry::RunTest(const FString& Parameters)
{
    FMRDistrictEnvironment Model;
    FMRDisturbance Fire;
    Fire.Id=TEXT("fire-1");Fire.Kind=EMRDisturbance::Fire;Fire.Time=20.;
    FMRDisturbance Smoke;
    Smoke.Id=TEXT("smoke-1");Smoke.Kind=EMRDisturbance::Smoke;Smoke.Time=30.;
    TestEqual(TEXT("fire smoke expires after 70 s"),HazardVisualEnd(Model,Fire,TEXT("HeavySmoke")),90.);
    TestEqual(TEXT("neighbouring smoke keeps its own 90 s lifetime"),HazardVisualEnd(Model,Smoke,TEXT("HeavySmoke")),120.);
    TestEqual(TEXT("smoke veil follows the smoke event"),HazardVisualEnd(Model,Smoke,TEXT("SmokeVeil")),120.);
    TestEqual(TEXT("fire survives its smoke"),HazardVisualEnd(Model,Fire,TEXT("BuildingFire")),-1.);
    TestEqual(TEXT("electrical onset is a short visual flash"),HazardVisualEnd(Model,Fire,TEXT("ElectricalIgnition")),20.8);
    Fire.ExpiresAt=80.;Fire.VisibilityExpiresAt=70.;
    TestEqual(TEXT("explicit fire smoke expiry"),HazardVisualEnd(Model,Fire,TEXT("HeavySmoke")),70.);
    TestEqual(TEXT("lamp follows the fire's effect expiry"),HazardVisualEnd(Model,Fire,TEXT("FireLight")),80.);
    TestEqual(TEXT("scorch persists as a consequence"),HazardVisualEnd(Model,Fire,TEXT("Scorch")),-1.);
    Fire.VisibilityExpiresAt=95.;
    TestEqual(TEXT("visual cannot outlast its expired event"),HazardVisualEnd(Model,Fire,TEXT("HeavySmoke")),80.);
    FMRDisturbance Fog;
    Fog.Kind=EMRDisturbance::LowVisibility;Fog.Time=31.;
    TestEqual(TEXT("fog expires after 100 s"),HazardVisualEnd(Model,Fog,TEXT("LowVisibility")),131.);
    TestEqual(TEXT("fog veil follows its different event"),HazardVisualEnd(Model,Fog,TEXT("FogVeil")),131.);
    Fog.ExpiresAt=50.;Fog.VisibilityExpiresAt=56.;
    TestEqual(TEXT("fog veil ends at earlier explicit boundary"),HazardVisualEnd(Model,Fog,TEXT("FogVeil")),50.);
    FMRDisturbance Flood;
    Flood.Kind=EMRDisturbance::Flood;Flood.Time=45.;Flood.ExpiresAt=55.;
    TestEqual(TEXT("leak follows the flood's effect expiry"),HazardVisualEnd(Model,Flood,TEXT("PipeLeak")),55.);
    FMRDisturbance Arrival;
    Arrival.Kind=EMRDisturbance::NewTarget;Arrival.Time=45.;
    TestEqual(TEXT("arrival pulse is brief"),HazardVisualEnd(Model,Arrival,TEXT("TargetArrival")),49.);
    return true;
}
#endif

FMRSurfaceState AMRWorld::QuerySurfaceMeters(FVector P) const
{
    P*=100;FMRSurfaceState State;State.MovementCost=MovementCost(P);
    State.WaterDepthMeters=WaterDepth(P)/100;State.Blocked=IsUnsafeGround(P);
    for(const auto& Box:StructureFootprints)if(Box.IsInside(P)){State.Blocked=true;break;}
    State.VisibilityQuality=VisibilityQuality(P);State.Revision=Environment.Revision;return State;
}
bool AMRWorld::SubmitRouteMeters(const FString& Key,const FString& Id,const TArray<FVector>& Points)
{
    TArray<FVector> Cm;for(const auto& P:Points)Cm.Add(P*100);
    for(AMRAgent* A:Agents)if(A->AgentKey()==Key)return A->AcceptRoute(Id,Cm);return false;
}
bool AMRWorld::HoldAgent(const FString& Key,const FString& Id)
{
    if(Id.IsEmpty())return false;
    for(AMRAgent* A:Agents)if(A->AgentKey()==Key)return A->Hold(Id);return false;
}
FString AMRWorld::PublicObservationJson() const
{
    auto J=MakeShared<FJsonObject>();J->SetStringField(TEXT("profile"),TEXT("unreal_local_adapter_v1_not_core_http"));
    J->SetNumberField(TEXT("time_s"),GetWorld()->GetTimeSeconds());
    TArray<TSharedPtr<FJsonValue>> Rows;
    for(const auto& T:Targets)if(T.bDiscovered)
    {
        auto Row=MakeShared<FJsonObject>();Row->SetNumberField(TEXT("id"),T.Id);
        Row->SetBoolField(TEXT("rescued"),T.bRescued);
        TArray<TSharedPtr<FJsonValue>> P;for(double V:{T.Position.X/100,T.Position.Y/100,T.Position.Z/100})P.Add(MakeShared<FJsonValueNumber>(V));
        Row->SetArrayField(TEXT("position_m"),P);Rows.Add(MakeShared<FJsonValueObject>(Row));
    }
    J->SetArrayField(TEXT("targets"),Rows);Rows.Empty();
    for(AMRAgent* A:Agents)
    {
        auto Row=MakeShared<FJsonObject>();Row->SetStringField(TEXT("id"),A->AgentKey());
        Row->SetStringField(TEXT("state"),A->State);Row->SetStringField(TEXT("command_id"),A->CommandId);
        Row->SetStringField(TEXT("stop_reason"),A->StopReason);
        const FVector P=A->GetActorLocation()/100,V=A->Body->GetPhysicsLinearVelocity()/100;
        TArray<TSharedPtr<FJsonValue>> Position,Velocity;
        for(double X:{P.X,P.Y,P.Z})Position.Add(MakeShared<FJsonValueNumber>(X));
        for(double X:{V.X,V.Y,V.Z})Velocity.Add(MakeShared<FJsonValueNumber>(X));
        Row->SetArrayField(TEXT("position_m"),Position);Row->SetArrayField(TEXT("velocity_m_s"),Velocity);
        Row->SetNumberField(TEXT("energy_wh"),A->Energy);Row->SetBoolField(TEXT("carrying"),A->bCarrying);
        Rows.Add(MakeShared<FJsonValueObject>(Row));
    }
    J->SetArrayField(TEXT("agents"),Rows);
    FString Text;FJsonSerializer::Serialize(J,TJsonWriterFactory<TCHAR,TCondensedJsonPrintPolicy<TCHAR>>::Create(&Text));return Text;
}
void AMRWorld::ExportEnvironmentManifest() const
{
    auto J=MakeShared<FJsonObject>();J->SetStringField(TEXT("kind"),TEXT("private_environment_truth_v3"));
    J->SetStringField(TEXT("mode"),Environment.Mode);J->SetNumberField(TEXT("seed"),Environment.Seed);
    J->SetNumberField(TEXT("window_s"),30);J->SetNumberField(TEXT("horizon_s"),Environment.Horizon);
    J->SetStringField(TEXT("coordinates"),TEXT("meters; X/Y match Unreal XY, Z up; origin at world actor; internal cm = m * 100"));
    auto Prob=MakeShared<FJsonObject>();for(int32 K=0;K<8;K++)Prob->SetNumberField(MRDisturbanceName(EMRDisturbance(K)),Environment.Probabilities[K]);
    J->SetObjectField(TEXT("probabilities_pct"),Prob);
    J->SetNumberField(TEXT("dynamic_cell_size_m"),MRDistrictSettings::CellCm/100);
    J->SetStringField(TEXT("rng"),TEXT("FRandomStream; v0.3 event semantics adapted to authored 3D sites, not Python MT19937 bitwise parity"));
    auto Bounds=MakeShared<FJsonObject>();
    TArray<TSharedPtr<FJsonValue>> Min,Max;
    for(double V:{-30.,-20.,-3.})Min.Add(MakeShared<FJsonValueNumber>(V));
    for(double V:{170.,170.,60.})Max.Add(MakeShared<FJsonValueNumber>(V));
    Bounds->SetArrayField(TEXT("min_m"),Min);Bounds->SetArrayField(TEXT("max_m"),Max);J->SetObjectField(TEXT("working_bounds"),Bounds);
    TArray<TSharedPtr<FJsonValue>> Rows;
    for(const auto& E:Environment.Tape)
    {
        auto Row=MakeShared<FJsonObject>();Row->SetStringField(TEXT("id"),E.Id);Row->SetStringField(TEXT("type"),MRDisturbanceName(E.Kind));
        if(E.Kind==EMRDisturbance::NewTarget)Row->SetNumberField(TEXT("target_id"),E.TargetId);
        Row->SetStringField(TEXT("site"),E.SiteId);Row->SetStringField(TEXT("parent_id"),E.ParentId);
        Row->SetNumberField(TEXT("time_s"),E.Time);Row->SetStringField(TEXT("rejected"),E.Rejection);
        TArray<TSharedPtr<FJsonValue>> Cells;for(auto C:E.Cells){TArray<TSharedPtr<FJsonValue>> XY;XY.Add(MakeShared<FJsonValueNumber>(C.X));XY.Add(MakeShared<FJsonValueNumber>(C.Y));Cells.Add(MakeShared<FJsonValueArray>(XY));}
        Row->SetArrayField(TEXT("cells"),Cells);Rows.Add(MakeShared<FJsonValueObject>(Row));
    }
    J->SetArrayField(TEXT("event_tape"),Rows);Rows.Empty();
    for(const auto& Box:StructureFootprints)
    {
        auto Row=MakeShared<FJsonObject>();TArray<TSharedPtr<FJsonValue>> Lo,Hi;
        for(double V:{Box.Min.X/100,Box.Min.Y/100,Box.Min.Z/100})Lo.Add(MakeShared<FJsonValueNumber>(V));
        for(double V:{Box.Max.X/100,Box.Max.Y/100,Box.Max.Z/100})Hi.Add(MakeShared<FJsonValueNumber>(V));
        Row->SetArrayField(TEXT("min_m"),Lo);Row->SetArrayField(TEXT("max_m"),Hi);Rows.Add(MakeShared<FJsonValueObject>(Row));
    }
    J->SetArrayField(TEXT("conservative_building_boxes"),Rows);
    Rows.Empty();
    FCollisionQueryParams Params(SCENE_QUERY_STAT(MRGeometryExport),false);
    for(AMRAgent* A:Agents)Params.AddIgnoredActor(A);
    for(int32 Y=-4;Y<34;Y++)for(int32 X=-6;X<34;X++)
    {
        const FVector P=FMRDistrictEnvironment::Center(FIntPoint(X,Y));FHitResult Ground;
        bool Solid=false;for(const auto& Box:StructureFootprints)if(Box.IsInsideXY(P)){Solid=true;break;}
        const bool Supported=GetWorld()->LineTraceSingleByChannel(Ground,P+FVector(0,0,9000),P-FVector(0,0,600),ECC_Visibility,Params);
        const float Height=Supported?Ground.ImpactPoint.Z:-1000;
        auto Row=MakeShared<FJsonObject>();Row->SetNumberField(TEXT("x"),X);Row->SetNumberField(TEXT("y"),Y);
        Row->SetNumberField(TEXT("surface_z_m"),Height/100);
        Row->SetBoolField(TEXT("blocked"),Solid||!Supported||Height<-80||IsUnsafeGround(P));
        Rows.Add(MakeShared<FJsonValueObject>(Row));
    }
    J->SetArrayField(TEXT("initial_ground_grid"),Rows);
    FString Text;FJsonSerializer::Serialize(J,TJsonWriterFactory<>::Create(&Text));
    FFileHelper::SaveStringToFile(Text,*(FPaths::ProjectSavedDir()/TEXT("Telemetry/environment-truth.json")),FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
}
