#include "MRCoreRuntime.h"
#include "MRCoreJson.h"
#include "MRCoreValues.h"
#include "MRWorld.h"
#include "MRAgent.h"
#include "MRUrbanWater.h"
#include "MRExplorationScene.h"
#include "MRMissionSession.h"
#include "Engine/World.h"
#include "Misc/Guid.h"
#include "Misc/App.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"

using namespace MRCoreValues;

void FMRCoreRuntime::ResetExploration()
{
    PendingExploration.Empty();ExplorationCursor.Empty();ExplorationView.Reset();
    ExplorationViewRevision=ExplorationViewStateRevision=ExplorationViewSceneRevision=-1;ExplorationScene.Reset();
    if(!World->bDisasterCity){Exploration.Reset(1,1,500,FVector2D::ZeroVector);return;}
    FVector Low=FVector::ZeroVector,High=FVector::ZeroVector;
    const auto Bounds=World->CityLayout->GetObjectField(TEXT("bounds"));
    MRCoreJson::Point(Field(Bounds,TEXT("min")),Low);MRCoreJson::Point(Field(Bounds,TEXT("max")),High);
    const FVector2D Origin(FMath::FloorToDouble(Low.X/5)*500,FMath::FloorToDouble(Low.Y/5)*500);
    if(!Exploration.Reset(FMath::CeilToInt((High.X*100-Origin.X)/500),
        FMath::CeilToInt((High.Y*100-Origin.Y)/500),500,Origin))
    {UE_LOG(LogTemp,Error,TEXT("MR_EXPLORATION invalid surface grid bounds"));Status=TEXT("failed");OutcomeReason=TEXT("invalid_exploration_grid");return;}
    auto KnownArea=[&](const Object& Area)
    {
        FVector A=FVector::ZeroVector,B=FVector::ZeroVector;
        if(MRCoreJson::Point(Field(Area,TEXT("min")),A)&&MRCoreJson::Point(Field(Area,TEXT("max")),B))
            Exploration.Grid.RevealBase(FBox(A*100,B*100));
    };
    KnownArea(World->CityLayout->GetObjectField(TEXT("base")));
    // The deployed base's own pier and launching gear are known before departure.
    if(const auto Station=World->ShoreStation())for(const auto& Platform:Station->GetArrayField(TEXT("platforms")))KnownArea(Platform->AsObject());
    if(Is(World->CityLayout,TEXT("watercraft"),EJson::Object))
        for(const auto& Value:World->CityLayout->GetObjectField(TEXT("watercraft"))->GetArrayField(TEXT("slipways")))
        {
            const auto Slip=Value->AsObject();const double X=Slip->GetNumberField(TEXT("x_m")),Half=Slip->GetNumberField(TEXT("width_m"))*.5;
            Exploration.Grid.RevealBase(FBox(FVector(X-Half,Slip->GetNumberField(TEXT("lower_y_m")),0)*100,
                FVector(X+Half,Slip->GetNumberField(TEXT("upper_y_m")),4)*100));
        }
}

void FMRCoreRuntime::GatherExplorationReport(AMRAgent* Agent)
{
    if(!World->bDisasterCity||Agent->Kind()==TEXT("underground")||Agent->Kind()==TEXT("underwater"))return;
    const FString Id=Agent->AgentKey();const FVector Pose=Agent->GetActorLocation();
    const double Range=100*SensorRadius.FindRef(Id),CellCm=Exploration.Grid.GetCellCm();
    const FIntPoint Origin=Exploration.Grid.CellAt(Pose);const int32 Radius=FMath::CeilToInt(Range/CellCm);
    const auto* Pending=PendingExploration.Find(Id);TArray<FIntPoint> Candidates;
    for(int32 Y=FMath::Max(0,Origin.Y-Radius);Y<FMath::Min(Exploration.Grid.GetHeight(),Origin.Y+Radius+1);++Y)
        for(int32 X=FMath::Max(0,Origin.X-Radius);X<FMath::Min(Exploration.Grid.GetWidth(),Origin.X+Radius+1);++X)
        {
            const FIntPoint Cell(X,Y);const int32 Key=Y*Exploration.Grid.GetWidth()+X;
            if(Pending&&Pending->Contains(Key))continue;
            // Open cells are revisited as well: remembered state must be sampled
            // again rather than following subsequent changes of the true scene.
            if(FVector::DistSquared2D(Pose,Exploration.Grid.Center(Cell))<=Range*Range)Candidates.Add(Cell);
        }
    if(Candidates.IsEmpty())return;
    const int32 Budget=FMath::Min(Agent->bAerial?48:24,Candidates.Num());int64& Cursor=ExplorationCursor.FindOrAdd(Id);
    FCollisionQueryParams SurfaceQuery(SCENE_QUERY_STAT(MRExplorationSurface),false);
    for(const auto& Other:World->Agents)SurfaceQuery.AddIgnoredActor(Other);
    for(const auto& Target:World->Targets)if(Target.Visual)SurfaceQuery.AddIgnoredActor(Target.Visual);
    FCollisionQueryParams Sight=SurfaceQuery;TArray<Value> Cells;TArray<FMRSeenSurface> Captured;
    for(int32 I=0;I<Budget;++I)
    {
        const auto Cell=Candidates[(Cursor+I)%Candidates.Num()];const FVector Center=Exploration.Grid.Center(Cell);
        FHitResult Surface,Blocker;
        if(!World->GetWorld()->LineTraceSingleByChannel(Surface,Center+FVector(0,0,12000),
            Center-FVector(0,0,3200),ECC_Visibility,SurfaceQuery))continue;
        const auto Water=World->WaterAtCm(Center);bool Wet=Water.InDomain&&Water.DepthCm>0&&Water.StageCm>Surface.ImpactPoint.Z;
        FVector Point=Wet?FVector(Center.X,Center.Y,Water.StageCm):Surface.ImpactPoint;
        FVector Normal=Wet?FVector::UpVector:Surface.ImpactNormal;
        UPrimitiveComponent* SurfacePart=Surface.GetComponent();
        FVector Endpoint=Point+FVector(0,0,Wet?5:35);
        if(World->GetWorld()->LineTraceSingleByChannel(Blocker,Pose,Endpoint,ECC_Visibility,Sight))
        {
            if(Exploration.Grid.CellAt(Blocker.ImpactPoint)!=Cell)continue;
            Point=Endpoint=Blocker.ImpactPoint;Normal=Blocker.ImpactNormal;Wet=false;
            SurfacePart=Blocker.GetComponent();
        }
        if(Exploration.Grid.CellAt(Point)!=Cell)continue;
        const double Quality=SensorQuality(Pose,Endpoint);
        if(Quality<.15||!SensorAccepts(Agent,Cell.Y*Exploration.Grid.GetWidth()+Cell.X,Quality,3))continue;
        FMRSeenSurface Sample;Sample.Cell=Cell;Sample.PointCm=Point;Sample.Normal=Normal;Sample.Quality=Quality;Sample.Water=Wet;
        Sample.ObservedAt=Time();Sample.Source=Id;Sample.SurfaceComponent=SurfacePart?SurfacePart->GetUniqueID():0;Captured.Add(Sample);
        Cells.Add(Json(Obj({{TEXT("cell"),Arr({Num(Cell.X),Num(Cell.Y)})},{TEXT("point_m"),MRCoreValues::Point(Point/100)},
            {TEXT("normal"),MRCoreValues::Point(Normal)},{TEXT("quality"),Num(Quality)},{TEXT("water"),Bool(Wet)},
            {TEXT("surface_component"),Num(Sample.SurfaceComponent)}})));
    }
    Cursor+=Budget;if(Cells.IsEmpty())return;
    FReport Packet;Packet.Kind=EPacket::Exploration;Packet.Agent=Id;Packet.Sequence=SensorSamples;
    Packet.MessageId=FGuid::NewGuid().ToString(EGuidFormats::Digits);
    Packet.Data=Obj({{TEXT("message_id"),Str(Packet.MessageId)},{TEXT("source_id"),Str(Id)},
        {TEXT("observed_at"),Num(Time())},{TEXT("sensor_origin_m"),MRCoreValues::Point(Pose/100)},
        {TEXT("footprint_radius_m"),Num(Range/100)},{TEXT("cells"),Arr(Cells)}});
    if(ExplorationScene)Packet.Scene=ExplorationScene->Capture(Exploration,Captured,Pose,Id,Time(),
        [this](FVector A,FVector B){return SensorQuality(A,B);});
    Record(TEXT("exploration_observation"),Packet.Data,false);QueueReport(MoveTemp(Packet));
}

void FMRCoreRuntime::TrackExplorationPacket(const FReport& Packet,bool Add)
{
    if(Packet.Kind!=EPacket::Exploration)return;
    auto& Pending=PendingExploration.FindOrAdd(Packet.Agent);
    for(const auto& Value:Packet.Data->GetArrayField(TEXT("cells")))
    {
        const auto& XY=Value->AsObject()->GetArrayField(TEXT("cell"));
        const int32 I=int32(XY[1]->AsNumber())*Exploration.Grid.GetWidth()+int32(XY[0]->AsNumber());
        if(Add)Pending.Add(I);else Pending.Remove(I);
    }
    if(Pending.IsEmpty())PendingExploration.Remove(Packet.Agent);
}

void FMRCoreRuntime::DeliverExplorationReport(const FReport& Packet)
{
    TArray<FMRSeenSurface> Samples;const int32 Before=Exploration.Grid.OpenCount();
    for(const auto& Value:Packet.Data->GetArrayField(TEXT("cells")))
    {
        const auto Row=Value->AsObject();const auto& XY=Row->GetArrayField(TEXT("cell"));FMRSeenSurface Sample;
        Sample.Cell=FIntPoint(int32(XY[0]->AsNumber()),int32(XY[1]->AsNumber()));
        MRCoreJson::Point(Field(Row,TEXT("point_m")),Sample.PointCm);Sample.PointCm*=100;
        MRCoreJson::Point(Field(Row,TEXT("normal")),Sample.Normal);Sample.Quality=Row->GetNumberField(TEXT("quality"));
        Sample.Water=Row->GetBoolField(TEXT("water"));Sample.ObservedAt=Packet.Data->GetNumberField(TEXT("observed_at"));
        Sample.ReceivedAt=Time();Sample.Source=Packet.Agent;Samples.Add(MoveTemp(Sample));
    }
    const int32 Updated=Exploration.Apply(Samples);
    if(ExplorationScene&&Packet.Scene)ExplorationScene->Apply(*Packet.Scene,Exploration);
    Record(TEXT("exploration_received"),Obj({{TEXT("message_id"),Str(Packet.MessageId)},
        {TEXT("source_id"),Str(Packet.Agent)},{TEXT("observed_at"),Field(Packet.Data,TEXT("observed_at"))},
        {TEXT("received_at"),Num(Time())},{TEXT("opened_cells"),Num(Exploration.Grid.OpenCount()-Before)},
        {TEXT("updated_cells"),Num(Updated)},{TEXT("revision"),Num(Exploration.Grid.GetRevision())},
        {TEXT("state_revision"),Num(Exploration.GetRevision())}}));
}

Object FMRCoreRuntime::ExplorationSnapshot()
{
    const auto& Grid=Exploration.Grid;
    const int32 SceneRevision=ExplorationScene?ExplorationScene->GetRevision():-1;
    if(ExplorationView&&ExplorationViewRevision==Grid.GetRevision()&&ExplorationViewStateRevision==Exploration.GetRevision()&&
        ExplorationViewSceneRevision==SceneRevision)return ExplorationView;
    TArray<Value> Spans;for(const auto& Span:Grid.RowSpans())Spans.Add(Arr({Num(Span.X),Num(Span.Y),Num(Span.Z)}));
    const auto Origin=Grid.GetOriginCm();
    ExplorationView=Obj({{TEXT("format"),Str(TEXT("metarescue.exploration.v1"))},{TEXT("cell_m"),Num(Grid.GetCellCm()/100)},
        {TEXT("origin_m"),Arr({Num(Origin.X/100),Num(Origin.Y/100)})},{TEXT("width"),Num(Grid.GetWidth())},
        {TEXT("height"),Num(Grid.GetHeight())},{TEXT("revision"),Num(Grid.GetRevision())},
        {TEXT("state_revision"),Num(Exploration.GetRevision())},{TEXT("opened_cells"),Num(Grid.OpenCount())},
        {TEXT("row_spans"),Arr(Spans)},{TEXT("persistence"),Str(TEXT("episode_permanent"))},
        {TEXT("source"),Str(TEXT("delivered_sensor_observations"))},{TEXT("surface_renderer_connected"),Bool(ExplorationScene.IsValid())}});
    if(ExplorationScene)ExplorationView->SetObjectField(TEXT("remembered_scene"),ExplorationScene->Snapshot());
    ExplorationViewRevision=Grid.GetRevision();ExplorationViewStateRevision=Exploration.GetRevision();ExplorationViewSceneRevision=SceneRevision;return ExplorationView;
}

void FMRCoreRuntime::ResetExplorationScene()
{
    if(!World->bDisasterCity||!FApp::CanEverRender())return;
    ExplorationScene=MakeShared<FMRExplorationScene>(World);ExplorationScene->Reset(Exploration);
    for(auto& Agent:World->Agents)ExplorationScene->ApplyActors(ExplorationScene->CaptureActor(Agent,0));
    RefreshExplorationView();
}
bool FMRCoreRuntime::IsKnowledgeView() const
{
    const auto* Session=UMRMissionSession::Get(World->GetWorld());
    if(Session&&Session->Enabled)return !Session->SetupOpen&&!Session->ObserverView;
    return FParse::Param(FCommandLine::Get(),TEXT("MRKnowledgeView"));
}
void FMRCoreRuntime::RefreshExplorationView()
{if(ExplorationScene)ExplorationScene->View(IsKnowledgeView(),Time());}
bool FMRCoreRuntime::DisplayPosition(const FString& Agent,FVector& PositionCm) const
{
    const auto Known=KnownAgents.FindRef(Agent);FVector P;
    if(!Known||!MRCoreJson::Point(Field(Known,TEXT("position")),P))return false;
    PositionCm=P*100;return true;
}
