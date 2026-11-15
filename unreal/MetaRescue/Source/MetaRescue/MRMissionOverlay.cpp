#include "MRMissionOverlay.h"
#include "MRHUD.h"
#include "MRWorld.h"
#include "MRMissionSession.h"
#include "MRCoreRuntime.h"
#include "MRCoreValues.h"
#include "MRCoreJson.h"
#include "MRAgent.h"
#include "Components/LineBatchComponent.h"
#include "ProceduralMeshComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Components/BoxComponent.h"
#include "Engine/StaticMesh.h"
#include "Engine/Canvas.h"
#include "Engine/Engine.h"
#include "Engine/World.h"
#include "GameFramework/PlayerController.h"
#include "Camera/PlayerCameraManager.h"
#include "Materials/MaterialInterface.h"

using namespace MRCoreValues;

namespace
{
constexpr int32 MaximumLines=6144,TrailLines=3072,MaximumAgents=128;
constexpr int32 MaximumLabels=32,MaximumMeasuredLabels=48;

struct FProjectedLabel
{
    FString Text, Id;
    FVector2D Anchor;
    FLinearColor Color;
    int32 Priority;
    bool AgentMarker;
};
FVector ReadPoint(const Value& ValueToRead){FVector P=FVector::ZeroVector;MRCoreJson::Point(ValueToRead,P);return P*100.;}
bool MobileKind(const FString& Kind){return Kind==TEXT("ground")||Kind==TEXT("aerial")||Kind==TEXT("underground")||Kind==TEXT("surface_water")||Kind==TEXT("underwater");}
FVector TracePosition(FVector P,const FString& Kind){if(Kind==TEXT("ground"))P.Z-=37;return P;}
}

FMRMissionOverlay::~FMRMissionOverlay()
{RestoreVisibility();if(VisualActor.IsValid())VisualActor->Destroy();}

void FMRMissionOverlay::RestoreVisibility()
{
    if(HUD.IsValid())if(auto* PC=HUD->GetOwningPlayerController())
        for(const auto& Actor:HiddenByView)if(Actor.IsValid())PC->HiddenActors.Remove(Actor.Get());
    HiddenByView.Reset();LastObserver=true;
}

void FMRMissionOverlay::Draw(UMRMissionSession* Session,UCanvas* Canvas)
{
    if(!HUD.IsValid())return;
    auto* CanvasHUD=HUD.Get();auto* PC=CanvasHUD->GetOwningPlayerController();
    if(!PC)return;
    if(Session->SetupOpen){if(Ribbons.IsValid())Ribbons->SetVisibility(false);if(KnowledgeFloor.IsValid())KnowledgeFloor->SetVisibility(false);RestoreVisibility();return;}
    auto* World=Session->Mission.Get();const auto O=Session->Observation();
    if(!World||!World->CoreRuntime||!O)return;
    const FString CurrentEpisode=Text(O,TEXT("episode_id"));
    if(Episode!=CurrentEpisode)
    {Episode=CurrentEpisode;TruthTraces.Empty();PublicTraces.Empty();LastTruthSample=-1;RestoreVisibility();}
    if(!VisualActor.IsValid())
    {
        auto* Actor=World->GetWorld()->SpawnActor<AActor>();Actor->SetActorEnableCollision(false);Actor->SetActorTickEnabled(false);VisualActor=Actor;
        auto* Mesh=NewObject<UProceduralMeshComponent>(Actor);Actor->SetRootComponent(Mesh);Actor->AddInstanceComponent(Mesh);
        Mesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);Mesh->SetCastShadow(false);Mesh->bAffectDistanceFieldLighting=false;
        Mesh->SetMaterial(0,LoadObject<UMaterialInterface>(nullptr,TEXT("/Game/RescueAssets/UIV1/M_TelemetryRibbon.M_TelemetryRibbon")));
        Mesh->RegisterComponent();Ribbons=Mesh;
        auto* Floor=NewObject<UStaticMeshComponent>(Actor);Actor->AddInstanceComponent(Floor);Floor->SetupAttachment(Mesh);
        Floor->SetStaticMesh(LoadObject<UStaticMesh>(nullptr,TEXT("/Engine/BasicShapes/Plane.Plane")));
        Floor->SetMaterial(0,LoadObject<UMaterialInterface>(nullptr,TEXT("/Game/RescueAssets/UIV1/M_KnowledgeBoard.M_KnowledgeBoard")));
        Floor->SetCollisionEnabled(ECollisionEnabled::NoCollision);Floor->SetCastShadow(false);Floor->bAffectDistanceFieldLighting=false;Floor->RegisterComponent();KnowledgeFloor=Floor;
    }
    if(LastObserver!=Session->ObserverView)
    {
        RestoreVisibility();
        if(!Session->ObserverView)
        {
            auto Hide=[&](AActor* Actor){if(Actor&&!PC->HiddenActors.Contains(Actor)){PC->HiddenActors.Add(Actor);HiddenByView.Add(Actor);}};
            // A schematic public view uses announced geometry only. In particular
            // new rubble, fire, private people and current offline poses are hidden
            // from this viewer without changing any simulation visibility flags.
            Hide(World);for(AMRAgent* Agent:World->Agents)Hide(Agent);for(const auto& T:World->Targets)Hide(T.Visual);
        }
        LastObserver=Session->ObserverView;
    }
    const auto Map=O->GetObjectField(TEXT("metaevolution"))->GetObjectField(TEXT("announced_map"));
    const auto Bounds=Map->GetObjectField(TEXT("bounds"));const FVector Lo=ReadPoint(Field(Bounds,TEXT("min"))),Hi=ReadPoint(Field(Bounds,TEXT("max")));
    KnowledgeFloor->SetVisibility(!Session->ObserverView);
    if(!Session->ObserverView)
    {KnowledgeFloor->SetWorldLocation(FVector((Lo.X+Hi.X)*.5,(Lo.Y+Hi.Y)*.5,-3));KnowledgeFloor->SetWorldScale3D(FVector((Hi.X-Lo.X)/100.,(Hi.Y-Lo.Y)/100.,1));}

    const double Time=World->CoreRuntime->Time();
    if(Time+1.e-8>=LastTruthSample+.1)
    {
        LastTruthSample=Time;
        for(AMRAgent* Agent:World->Agents)if(Agent->CanMove()&&(TruthTraces.Contains(Agent->AgentKey())||TruthTraces.Num()<MaximumAgents))
            TruthTraces.FindOrAdd(Agent->AgentKey()).Add(Time,TracePosition(Agent->GetActorLocation(),Agent->Kind()));
    }
    TMap<FString,Object> Known;
    TMap<FString,FVector> Positions;
    for(const auto& Value:O->GetArrayField(TEXT("agents")))
    {
        const auto Agent=Value->AsObject();const FString Id=Text(Agent,TEXT("id"));Known.Add(Id,Agent);
        if(!Is(Agent,TEXT("position"),EJson::Array))continue;
        const FVector P=ReadPoint(Field(Agent,TEXT("position")));Positions.Add(Id,P);
        const auto Stamp=Agent->GetObjectField(TEXT("freshness"))->GetObjectField(TEXT("position"));double At=0;
        if(MobileKind(Text(Agent,TEXT("kind")))&&Stamp->TryGetNumberField(TEXT("observed_at"),At)&&
            (PublicTraces.Contains(Id)||PublicTraces.Num()<MaximumAgents))PublicTraces.FindOrAdd(Id).Add(At,TracePosition(P,Text(Agent,TEXT("kind"))),true);
    }
    for(const auto& Value:O->GetArrayField(TEXT("infrastructure")))
    {const auto Node=Value->AsObject();if(Is(Node,TEXT("position"),EJson::Array))Positions.Add(Text(Node,TEXT("id")),ReadPoint(Field(Node,TEXT("position"))));}

    TArray<FBatchedLine> Lines;Lines.Reserve(MaximumLines);
    const int32 MarkerReserve=Session->ObserverView?0:FMath::Min(2048,Positions.Num()*6+O->GetArrayField(TEXT("targets")).Num()*2+32);
    int32 LineLimit=MaximumLines-MarkerReserve;
    auto Line=[&](const FVector& A,const FVector& B,const FLinearColor& Color,float Width=1.5f)
    {if(Lines.Num()>=LineLimit)return false;Lines.Emplace(A,B,Color,-1.f,Width,SDPG_World);return true;};
    auto Dashed=[&](const FVector& A,const FVector& B,const FLinearColor& Color)
    {const double Length=FVector::Distance(A,B);const int32 Parts=FMath::Clamp(FMath::CeilToInt(Length/250.),1,80);for(int32 I=0;I<Parts;I+=2)if(!Line(FMath::Lerp(A,B,double(I)/Parts),FMath::Lerp(A,B,double(FMath::Min(I+1,Parts))/Parts),Color,1.25f))break;};
    auto Rectangle=[&](const FVector& A,const FVector& B,const FLinearColor& Color,float Width=1.5f)
    {const FVector P[]={A,FVector(B.X,A.Y,A.Z),FVector(B.X,B.Y,A.Z),FVector(A.X,B.Y,A.Z)};for(int32 I=0;I<4;I++)Line(P[I],P[(I+1)%4],Color,Width);};
    auto Box=[&](const FVector& A,const FVector& B,const FLinearColor& Color)
    {Rectangle(A,B,Color);Rectangle(FVector(A.X,A.Y,B.Z),B,Color);for(int32 X=0;X<2;X++)for(int32 Y=0;Y<2;Y++)Line(FVector(X?B.X:A.X,Y?B.Y:A.Y,A.Z),FVector(X?B.X:A.X,Y?B.Y:A.Y,B.Z),Color);};
    const FVector2D LabelMinimum(Session->CaptureOverview?24:245,95);
    const FVector2D LabelMaximum(Canvas->ClipX-(Session->InspectorOpen?375:24),Canvas->ClipY-55);
    const FBox2D LabelArea(LabelMinimum,LabelMaximum);
    TArray<FProjectedLabel> Labels;
    auto Label=[&](const FString& TextToShow,const FString& Id,const FVector& At,const FLinearColor& Color,
                   int32 Priority,bool AgentMarker=false)
    {
        FVector2D Screen;
        if(LabelMaximum.X<=LabelMinimum.X||LabelMaximum.Y<=LabelMinimum.Y||
           !PC->ProjectWorldLocationToScreen(At,Screen)||!LabelArea.IsInside(Screen))return;
        Labels.Add({TextToShow.Left(48),Id,Screen,Color,Priority,AgentMarker});
    };
    int32 TrailCount=0,TruthPoints=0,PublicPoints=0;
    for(const auto& Pair:TruthTraces)TruthPoints+=Pair.Value.Points.Num();for(const auto& Pair:PublicTraces)PublicPoints+=Pair.Value.Points.Num();
    if(Session->ShowTrails)
    {
        const auto& History=Session->ObserverView?TruthTraces:PublicTraces;
        const int32 Stride=FMath::Max(1,FMath::CeilToInt(double(Session->ObserverView?TruthPoints:PublicPoints)/TrailLines));
        TArray<FString> Ids;History.GetKeys(Ids);Ids.Sort();
        for(const FString& Id:Ids)
        {
            const auto& Points=History.FindChecked(Id).Points;const FLinearColor Color=MRDisplayColor(Id).CopyWithNewOpacity(.8f);
            int32 From=0;
            for(int32 I=1;I<Points.Num();I++)
            {
                if(!Points[I].Connected){From=I;continue;}
                if(I-From>=Stride||I==Points.Num()-1){if(TrailCount<TrailLines){Line(Points[From].Position,Points[I].Position,Color,3.f);++TrailCount;}From=I;}
            }
        }
    }
    if(Session->ShowRoutes)
    {
        if(Session->ObserverView)
        {
        for(AMRAgent* Agent:World->Agents)if(Agent->CanMove())
        {FVector Previous=TracePosition(Agent->GetActorLocation(),Agent->Kind());for(const FVector& Point:Agent->RemainingRouteForInterface())
            {if(Lines.Num()>=MaximumLines-1024)break;const FVector Next=TracePosition(Point,Agent->Kind());Dashed(Previous,Next,MRDisplayColor(Agent->AgentKey()).CopyWithNewOpacity(.55f));Previous=Next;}}
        }
        else for(const auto& Value:World->CoreRuntime->PublicRoutesForInterface())
        {
            const auto Route=Value->AsObject();const FString Id=Text(Route,TEXT("agent_id"));const auto Agent=Known.FindRef(Id);
            if(!Agent||!Positions.Contains(Id))continue;
            const auto& Points=Route->GetArrayField(TEXT("waypoints"));int32 First=0;
            const bool Confirmed=Text(Route,TEXT("delivery_status"))==TEXT("delivered");
            if(Confirmed&&Is(Agent,TEXT("physical"),EJson::Object))
            {const auto Physical=Agent->GetObjectField(TEXT("physical"));const FVector Waypoint=ReadPoint(Field(Physical,TEXT("active_waypoint")));
                for(int32 I=0;I<Points.Num();I++)if(ReadPoint(Points[I]).Equals(Waypoint,.05)){First=I;break;}}
            FVector Previous=TracePosition(Positions.FindChecked(Id),Text(Agent,TEXT("kind")));
            for(int32 I=First;I<Points.Num()&&Lines.Num()<MaximumLines-1024;I++)
            {const FVector Next=TracePosition(ReadPoint(Points[I]),Text(Agent,TEXT("kind")));Dashed(Previous,Next,Confirmed?MRDisplayColor(Id):FLinearColor(.9f,.65f,.25f));Previous=Next;}
        }
    }
    if(Session->ShowNetwork)
    {
        for(const auto& Value:O->GetObjectField(TEXT("network"))->GetArrayField(TEXT("known_links")))
        {const auto Link=Value->AsObject();const auto* A=Positions.Find(Text(Link,TEXT("from")));const auto* B=Positions.Find(Text(Link,TEXT("to")));
            if(A&&B)Dashed(*A+FVector(0,0,130),*B+FVector(0,0,130),FLinearColor(.15f,.85f,.85f));}
    }
    if(Session->ShowHazards)for(const auto& Value:O->GetArrayField(TEXT("zones")))
    {
        const auto Zone=Value->AsObject();const auto Geometry=Zone->GetObjectField(TEXT("geometry"));
        if(!Geometry||!Is(Geometry,TEXT("min"),EJson::Array)||!Is(Geometry,TEXT("max"),EJson::Array))continue;
        const FString Type=Text(Zone,TEXT("type"));if(Type!=TEXT("hazard")&&Type!=TEXT("water")&&Type!=TEXT("restricted"))continue;
        FVector A=ReadPoint(Field(Geometry,TEXT("min"))),B=ReadPoint(Field(Geometry,TEXT("max")));A.Z=FMath::Max(A.Z,6.);B.Z=FMath::Max(B.Z,18.);
        Box(A,B,Type==TEXT("water")?FLinearColor(.15f,.55f,.9f):FLinearColor(.95f,.3f,.12f));
        if(Lines.Num()>MaximumLines-128)break;
    }
    if(Session->ShowHazards)
    {
        const auto Extension=O->GetObjectField(TEXT("metaevolution"));
        if(Is(Extension,TEXT("orbital_observation"),EJson::Object))
        {
            const auto Orbit=Extension->GetObjectField(TEXT("orbital_observation"));
            const double At=Orbit->GetNumberField(TEXT("observed_at"));
            if(At<=Time&&Time-At<=10.)
            {
                const FVector Center=ReadPoint(Field(Orbit,TEXT("ground_track_m")))+FVector(0,0,25);
                const double Radius=Orbit->GetNumberField(TEXT("swath_radius_m"))*100.;
                const FLinearColor Cyan(.28f,.84f,1);
                FVector Previous=Center+FVector(Radius,0,0);
                for(int32 I=1;I<=24;++I)
                {
                    const double Angle=I*UE_DOUBLE_TWO_PI/24.;
                    const FVector Next=Center+Radius*FVector(FMath::Cos(Angle),FMath::Sin(Angle),0);
                    if(!Line(Previous,Next,Cyan,2.f))break;
                    Previous=Next;
                }
                Label(TEXT("ORBITAL PASS"),TEXT("orbital-pass"),Center+FVector(0,0,150),Cyan,4);
            }
        }
    }
    if(Session->ShowCoverage&&Session->Health&&Is(Session->Health,TEXT("planning"),EJson::Object))
    {
        const auto Planning=Session->Health->GetObjectField(TEXT("planning"));
        if(Is(Planning,TEXT("covered_regions"),EJson::Array))for(const auto& Value:Planning->GetArrayField(TEXT("covered_regions")))
        {const auto Region=Value->AsObject();Rectangle(ReadPoint(Field(Region,TEXT("min"))),ReadPoint(Field(Region,TEXT("max"))),FLinearColor(.4f,.85f,.25f));if(Lines.Num()>MaximumLines-128)break;}
    }
    if(Session->ShowScenarios)
    {
        TArray<FVector> Coalition;
        for(const auto& Pair:Known)if(Positions.Contains(Pair.Key))
        {const FString Role=Text(Pair.Value,TEXT("role"));
            if(Role==TEXT("executor")||Role==TEXT("relay"))Coalition.Add(Positions.FindChecked(Pair.Key)+FVector(0,0,150));}
        if(Coalition.Num()>1)for(int32 I=1;I<Coalition.Num();I++)Dashed(Coalition[0],Coalition[I],FLinearColor(.8f,.65f,.95f));
    }
    int32 BuildingWires=0;
    if(!Session->ObserverView)
    {
        Rectangle(FVector(Lo.X,Lo.Y,8),FVector(Hi.X,Hi.Y,8),FLinearColor(.4f,.5f,.4f));
        // Select visible declared volumes by distance to the viewport centre.
        TArray<TPair<double,Object>> Visible;
        for(const auto& Value:Map->GetArrayField(TEXT("buildings")))
        {const auto B=Value->AsObject()->GetObjectField(TEXT("bounds"));const FVector A=ReadPoint(Field(B,TEXT("min"))),Z=ReadPoint(Field(B,TEXT("max")));FVector2D Screen;
            if(PC->ProjectWorldLocationToScreen((A+Z)*.5,Screen)&&Screen.X>=-100&&Screen.Y>=-100&&Screen.X<=Canvas->ClipX+100&&Screen.Y<=Canvas->ClipY+100)
                Visible.Add({FVector2D::DistSquared(Screen,FVector2D(Canvas->ClipX*.5,Canvas->ClipY*.5)),B});}
        Visible.Sort([](const auto& A,const auto& B){return A.Key<B.Key;});
        for(const auto& Pair:Visible){if(Lines.Num()>MaximumLines-192)break;Box(ReadPoint(Field(Pair.Value,TEXT("min"))),ReadPoint(Field(Pair.Value,TEXT("max"))),FLinearColor(.38f,.45f,.41f));++BuildingWires;}
        if(Is(Map,TEXT("road_graph"),EJson::Object))
        {
            const auto Roads=Map->GetObjectField(TEXT("road_graph"));TMap<FString,FVector> Nodes;
            for(const auto& Value:Roads->GetArrayField(TEXT("nodes")))Nodes.Add(Text(Value->AsObject(),TEXT("id")),ReadPoint(Field(Value->AsObject(),TEXT("position")))+FVector(0,0,8));
            for(const auto& Value:Roads->GetArrayField(TEXT("edges")))
            {const auto Edge=Value->AsObject();const auto* A=Nodes.Find(Text(Edge,TEXT("from")));const auto* B=Nodes.Find(Text(Edge,TEXT("to")));if(A&&B)Line(*A,*B,FLinearColor(.58f,.64f,.59f),2.f);if(Lines.Num()>=LineLimit)break;}
        }
        LineLimit=MaximumLines;
        for(const auto& Pair:Known)if(Positions.Contains(Pair.Key))
        {
            const auto P=Positions.FindChecked(Pair.Key);const auto Color=MRDisplayColor(Pair.Key);const double Radius=Text(Pair.Value,TEXT("kind"))==TEXT("aerial")?120:95;
            Rectangle(P+FVector(-Radius,-Radius,8),P+FVector(Radius,Radius,8),Color,2.5f);Line(P+FVector(0,0,-15),P+FVector(0,0,150),Color,2.5f);
            FString Name=Pair.Key;
            const FString Role=Session->ShowScenarios?Text(Pair.Value,TEXT("role")):FString();
            if(!Role.IsEmpty())Name+=TEXT(" · ")+Role;
            const auto Physical=Is(Pair.Value,TEXT("physical"),EJson::Object)?Pair.Value->GetObjectField(TEXT("physical")):Object();
            const bool bLoaded=Is(Physical,TEXT("cargo_target_id"),EJson::String);
            const int32 Priority=Pair.Key==Session->SelectedAgent?6:bLoaded?5:!Role.IsEmpty()?3:1;
            Label(Name,Pair.Key,P+FVector(0,0,170),Color,Priority,true);
        }
        for(const auto& Value:O->GetArrayField(TEXT("targets")))
        {const auto Target=Value->AsObject();if(Text(Target,TEXT("evacuation_state"))==TEXT("evacuated")||!Is(Target,TEXT("position"),EJson::Array))continue;
            const FVector P=ReadPoint(Field(Target,TEXT("position")));Line(P+FVector(-75,0,20),P+FVector(75,0,20),FLinearColor(1,.4f,.2f),3);Line(P+FVector(0,-75,20),P+FVector(0,75,20),FLinearColor(1,.4f,.2f),3);const FString Id=Text(Target,TEXT("id"));Label(Id,Id,P+FVector(0,0,120),FLinearColor(1,.5f,.3f),4);}
    }
    else
    {
        for(AMRAgent* Agent:World->Agents)if(Agent->CanMove()||(Session->CaptureOverview&&MobileKind(Agent->Kind())))
        {
            const FString Id=Agent->AgentKey();
            FString Name=Id;
            const auto Observed=Known.FindRef(Id);
            const FString Role=Session->ShowScenarios&&Observed?Text(Observed,TEXT("role")):FString();
            FLinearColor Color=MRDisplayColor(Id);
            if(Session->CaptureOverview)
            {
                Name=(Agent->bAerial?TEXT("UAV "):TEXT("ROVER "))+Name;
                if(!Agent->IsOperational()){Name+=TEXT("  OFFLINE");Color=FLinearColor(1,.33f,.22f);}
            }
            if(!Role.IsEmpty())Name+=TEXT(" · ")+Role;
            const int32 Priority=Id==Session->SelectedAgent?6:Agent->bCarrying||!Agent->IsOperational()?5:
                !Role.IsEmpty()?3:Agent->GetVelocity().SizeSquared()>2500.?2:1;
            Label(Name,Id,Agent->GetActorLocation()+FVector(0,0,155),Color,Priority,true);
        }
        if(Session->CaptureOverview)Label(TEXT("RESCUE BASE"),TEXT("rescue-base"),World->Base+FVector(0,0,380),FLinearColor(.68f,1,.55f),7);
    }
    Labels.Sort([](const FProjectedLabel& A,const FProjectedLabel& B)
    {return A.Priority!=B.Priority?A.Priority>B.Priority:A.Id<B.Id;});
    TArray<FBox2D> Placed;
    Placed.Reserve(MaximumLabels);
    int32 Measured=0,MarkedAgents=0;
    const float LabelScale=Session->CaptureOverview?1.f:.9f;
    UFont* LabelFont=GEngine->GetSmallFont();
    for(const FProjectedLabel& Entry:Labels)
    {
        if(Entry.AgentMarker&&MarkedAgents<MaximumAgents&&LabelArea.IsInside(Entry.Anchor-FVector2D(3,3))&&
            LabelArea.IsInside(Entry.Anchor+FVector2D(3,3)))
        {
            CanvasHUD->DrawRect(Entry.Color,float(Entry.Anchor.X)-3,float(Entry.Anchor.Y)-3,6,6);
            ++MarkedAgents;
        }
        if(Placed.Num()>=MaximumLabels||Measured>=MaximumMeasuredLabels||Entry.Text.IsEmpty())continue;
        float Width=0,Height=0;
        CanvasHUD->GetTextSize(Entry.Text,Width,Height,LabelFont,LabelScale);
        ++Measured;
        const FVector2D Size(Width+8,Height+4);
        const double Left=-Size.X-8,Above=-Size.Y-7,Middle=-Size.Y*.5;
        const FVector2D Offsets[]={{8,Middle},{Left,Middle},{8,Above},{Left,Above},{8,7},{Left,7},{8,27},{Left,27}};
        for(const FVector2D& Offset:Offsets)
        {
            const FVector2D TopLeft=Entry.Anchor+Offset;
            const FBox2D LabelBounds(TopLeft-FVector2D(2,2),TopLeft+Size+FVector2D(2,2));
            if(!LabelArea.IsInside(LabelBounds.Min)||!LabelArea.IsInside(LabelBounds.Max)||
               Placed.ContainsByPredicate([&LabelBounds](const FBox2D& Other){return LabelBounds.Intersect(Other);}))continue;
            Placed.Add(LabelBounds);
            const FVector2D Edge(FMath::Clamp(Entry.Anchor.X,TopLeft.X,TopLeft.X+Size.X),
                                FMath::Clamp(Entry.Anchor.Y,TopLeft.Y,TopLeft.Y+Size.Y));
            CanvasHUD->DrawLine(float(Entry.Anchor.X),float(Entry.Anchor.Y),float(Edge.X),float(Edge.Y),Entry.Color,1);
            CanvasHUD->DrawRect(FLinearColor(.015f,.025f,.022f,.8f),float(TopLeft.X),float(TopLeft.Y),float(Size.X),float(Size.Y));
            CanvasHUD->DrawText(Entry.Text,Entry.Color,float(TopLeft.X)+4,float(TopLeft.Y)+2,LabelFont,LabelScale);
            break;
        }
    }
    // Runtime geometry is independent of the engine's debug PDI/compositing path.
    // Width is expressed in screen pixels, retaining real 3D depth and height.
    FVector Eye;FRotator ViewRotation;PC->GetPlayerViewPoint(Eye,ViewRotation);
    float FieldOfView=48;if(PC->PlayerCameraManager)FieldOfView=PC->PlayerCameraManager->GetFOVAngle();
    const double PixelFactor=FMath::Tan(FMath::DegreesToRadians(double(FieldOfView)*.5))/FMath::Max(1.,double(Canvas->ClipX));
    TArray<FVector> Vertices,Normals;TArray<int32> Triangles;TArray<FVector2D> UV;TArray<FLinearColor> Colors;
    Vertices.Reserve(Lines.Num()*4);Triangles.Reserve(Lines.Num()*6);Normals.Reserve(Lines.Num()*4);UV.Reserve(Lines.Num()*4);Colors.Reserve(Lines.Num()*4);
    for(const auto& Segment:Lines)
    {
        const FVector Along=Segment.End-Segment.Start;const FVector Mid=(Segment.Start+Segment.End)*.5;
        FVector Side=FVector::CrossProduct(Along,Eye-Mid).GetSafeNormal();
        if(Side.IsNearlyZero())Side=ViewRotation.RotateVector(FVector::RightVector);
        Side*=FMath::Max(1.,FVector::Distance(Eye,Mid)*PixelFactor*Segment.Thickness);
        const int32 Offset=Vertices.Num();Vertices.Append({Segment.Start-Side,Segment.Start+Side,Segment.End+Side,Segment.End-Side});
        const FVector Normal=(Eye-Mid).GetSafeNormal();
        for(int32 I=0;I<4;I++){Normals.Add(Normal);Colors.Add(Segment.Color);UV.Add(FVector2D(I>=2?1:0,I==1||I==2?1:0));}
        Triangles.Append({Offset,Offset+1,Offset+2,Offset,Offset+2,Offset+3});
    }
    Ribbons->SetVisibility(!Lines.IsEmpty());
    if(!Lines.IsEmpty())
    {
        if(RibbonLineCount==Lines.Num())Ribbons->UpdateMeshSection_LinearColor(0,Vertices,Normals,UV,Colors,TArray<FProcMeshTangent>());
        else Ribbons->CreateMeshSection_LinearColor(0,Vertices,Triangles,Normals,UV,Colors,TArray<FProcMeshTangent>(),false);
        RibbonLineCount=Lines.Num();
    }
    if(++Frames%20==0)Session->DisplayMetrics=Obj({{TEXT("basis"),Str(Session->ObserverView?TEXT("physical_observer"):TEXT("delivered_knowledge"))},
        {TEXT("truth_points"),Num(TruthPoints)},{TEXT("public_points"),Num(PublicPoints)},
        {TEXT("line_count"),Num(Lines.Num())},{TEXT("line_limit"),Num(MaximumLines)},{TEXT("trail_lines"),Num(TrailCount)},
        {TEXT("renderer"),Str(TEXT("runtime_vertex_color_ribbons.v1"))},{TEXT("vertices"),Num(Vertices.Num())},
        {TEXT("hidden_physical_actors"),Num(HiddenByView.Num())},{TEXT("building_wires"),Num(BuildingWires)},
        {TEXT("point_limit_per_agent_per_basis"),Num(FMRDisplayTrace::MaximumPoints)},
        {TEXT("placed_labels"),Num(Placed.Num())},{TEXT("measured_labels"),Num(Measured)},
        {TEXT("agent_markers"),Num(MarkedAgents)}});
}
