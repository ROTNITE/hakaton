#include "MRCoreRuntime.h"
#include "MRCoreJson.h"
#include "MRCoreValues.h"
#include "MRWorld.h"
#include "MRAgent.h"
#include "MRCameraPawn.h"
#include "Engine/GameViewportClient.h"
#include "Engine/World.h"
#include "Kismet/GameplayStatics.h"
#include "HAL/PlatformFileManager.h"
#include "Misc/Crc.h"
#include "Misc/Guid.h"
#include "NiagaraComponent.h"
#include "ProceduralMeshComponent.h"

using namespace MRCoreValues;

namespace
{
bool Number(const Object& Data,const TCHAR* Key,double& Out)
{
    const auto V=Field(Data,Key);
    if(!V||V->Type!=EJson::Number||!FMath::IsFinite(V->AsNumber()))return false;
    Out=V->AsNumber();return true;
}

bool Integer(const Object& Data,const TCHAR* Key,int32& Out)
{
    double Value=0;
    if(!Number(Data,Key,Value)||Value<0||Value>MAX_int32||Value!=FMath::FloorToDouble(Value))return false;
    Out=int32(Value);return true;
}

bool OptionalTime(const Object& Data,const TCHAR* Key,double StartsAt,double& Out)
{
    if(Is(Data,Key,EJson::Null)){Out=-1;return true;}
    return Number(Data,Key,Out)&&Out>StartsAt;
}

TArray<Value> CellsJson(const FMRDisturbance& Event)
{
    TArray<Value> Cells;
    for(const auto& Cell:Event.Cells)Cells.Add(Arr({Num(Cell.X),Num(Cell.Y)}));
    return Cells;
}
}

bool AMRWorld::ReadCoreEventTape()
{
    if(!bCityLayout||!CityLayout->HasField(TEXT("event_model")))return true;
    auto Fail=[](const TCHAR* Reason)
    {
        UE_LOG(LogTemp,Error,TEXT("MR_CORE invalid private event tape: %s"),Reason);
        return false;
    };
    if(!Is(CityLayout,TEXT("event_model"),EJson::Object))return Fail(TEXT("event_model must be an object"));
    const auto Model=CityLayout->GetObjectField(TEXT("event_model"));
    const auto Settings=CityLayout->GetObjectField(TEXT("settings"));
    const FString Profile=Text(Model,TEXT("profile"));
    const bool V052=Profile==TEXT("v052");
    double Horizon=0,Size=0,Window=0,Cell=0;
    if(Text(Model,TEXT("format"))!=TEXT("metarescue.events-3d.1.0")||
       (!V052&&Profile!=TEXT("v3"))||Profile!=Text(Settings,TEXT("event_profile"))||
       !Number(Model,TEXT("probability_window_s"),Window)||Window!=(V052?80:30)||
       !Number(Model,TEXT("physics_cell_m"),Cell)||Cell!=5||
       !Number(Settings,TEXT("horizon"),Horizon)||Horizon<1||Horizon>86400||
       !Number(CityLayout,TEXT("size_m"),Size)||Size<250||Size>1500||
       !Is(Model,TEXT("events"),EJson::Array)||!Is(Model,TEXT("late_people"),EJson::Array))
        return Fail(TEXT("version, profile, geometry or limits are invalid"));
    const auto& Rows=Model->GetArrayField(TEXT("events"));
    const auto& Late=Model->GetArrayField(TEXT("late_people"));
    if(Rows.Num()>100000||Late.Num()>2880)return Fail(TEXT("tape is larger than declared limits"));
    FVector BaseMin,BaseMax;
    const auto BaseBox=CityLayout->GetObjectField(TEXT("base"));
    if(!MRCoreJson::Point(Field(BaseBox,TEXT("min")),BaseMin)||!MRCoreJson::Point(Field(BaseBox,TEXT("max")),BaseMax))
        return Fail(TEXT("invalid protected base bounds"));
    auto SafePosition=[&](const FVector& Point,double Margin)
    {
        return Point.X>=0&&Point.Y>=0&&Point.X<=Size&&Point.Y<=Size&&
            !(Point.X>=BaseMin.X-Margin&&Point.X<=BaseMax.X+Margin&&Point.Y>=BaseMin.Y-Margin&&Point.Y<=BaseMax.Y+Margin);
    };
    TSet<int32> InitialIds;
    TMap<FIntPoint,TArray<FVector2D>> Occupied;
    auto Bucket=[](const FVector& P){return FIntPoint(FMath::FloorToInt(P.X/2.2),FMath::FloorToInt(P.Y/2.2));};
    TArray<Value> People=Scenario->GetArrayField(TEXT("people"));
    for(const auto& Item:People)
    {
        const auto Person=Item->AsObject();
        InitialIds.Add(Person->GetIntegerField(TEXT("id")));
        const FVector P(10*Person->GetNumberField(TEXT("x")),10*Person->GetNumberField(TEXT("y")),0);
        Occupied.FindOrAdd(Bucket(P)).Add(FVector2D(P.X,P.Y));
    }
    TMap<int32,Object> LateById;
    for(const auto& Value:Late)
    {
        if(Value->Type!=EJson::Object)return Fail(TEXT("invalid late person"));
        const auto Person=Value->AsObject();
        int32 Id=0,Priority=0;
        double AvailableAt=0;
        FVector P;
        if(!Integer(Person,TEXT("id"),Id)||Id<=0||InitialIds.Contains(Id)||LateById.Contains(Id)||
           !Integer(Person,TEXT("priority"),Priority)||Priority<1||Priority>3||
           !Number(Person,TEXT("available_at"),AvailableAt)||AvailableAt<=0||AvailableAt>=Horizon||
           !MRCoreJson::Point(Field(Person,TEXT("position")),P)||!SafePosition(P,8)||
           P.Z<-.25||P.Z>.6||Text(Person,TEXT("appearance_event_id")).IsEmpty())
            return Fail(TEXT("late person ID, position, priority or time is invalid"));
        const auto Key=Bucket(P);
        for(int32 X=-1;X<=1;X++)for(int32 Y=-1;Y<=1;Y++)
            if(const auto* Neighbours=Occupied.Find(Key+FIntPoint(X,Y)))
                for(const auto& Other:*Neighbours)
                    if(FVector2D::Distance(FVector2D(P.X,P.Y),Other)<2.2)return Fail(TEXT("overlapping late person"));
        Occupied.FindOrAdd(Key).Add(FVector2D(P.X,P.Y));
        LateById.Add(Id,Person);
        People.Add(Json(Obj({{TEXT("id"),Num(Id)},{TEXT("x"),Num(P.X/10)},{TEXT("y"),Num(P.Y/10)},
            {TEXT("z_m"),Num(P.Z)},{TEXT("available_at"),Num(AvailableAt)},
            {TEXT("priority"),Num(Priority/3.)},{TEXT("path"),Arr({})}})));
    }

    TArray<FMRDisturbance> Tape;
    TMap<FString,int32> Earlier;
    TSet<int32> ReferencedPeople;
    double Previous=0;
    for(const auto& Value:Rows)
    {
        if(Value->Type!=EJson::Object)return Fail(TEXT("event must be an object"));
        const auto Row=Value->AsObject();
        FMRDisturbance Event;
        Event.Id=Text(Row,TEXT("id"));
        Event.ParentId=Text(Row,TEXT("parent_id"));
        Event.SiteId=Text(Row,TEXT("source_object_id"));
        Event.Rejection=Text(Row,TEXT("rejection"));
        const FString Kind=Text(Row,TEXT("kind"));
        int32 KindIndex=0;
        while(KindIndex<8&&Kind!=MRDisturbanceName(EMRDisturbance(KindIndex)))++KindIndex;
        if(KindIndex>=8||(V052&&KindIndex==int32(EMRDisturbance::LowVisibility))||
           Event.Id.IsEmpty()||Event.Id.Len()>128||Earlier.Contains(Event.Id)||
           !Number(Row,TEXT("time"),Event.Time)||Event.Time<=0||Event.Time<Previous||Event.Time>=Horizon||
           !Is(Row,TEXT("spread"),EJson::Boolean)||!Is(Row,TEXT("cells"),EJson::Array)||
           !(Is(Row,TEXT("rejection"),EJson::Null)||!Event.Rejection.IsEmpty()))
            return Fail(TEXT("event ID, type, time or cells are invalid"));
        Event.Kind=EMRDisturbance(KindIndex);
        Event.bPropagation=Row->GetBoolField(TEXT("spread"));
        if(Event.bPropagation)
        {
            const auto* Parent=Earlier.Find(Event.ParentId);
            if(!Parent||Tape[*Parent].Time>=Event.Time||Tape[*Parent].Kind!=Event.Kind||
               !Tape[*Parent].Rejection.IsEmpty()||(Event.Kind!=EMRDisturbance::Fire&&Event.Kind!=EMRDisturbance::Flood))
                return Fail(TEXT("invalid propagation parent"));
        }
        else if(!Event.ParentId.IsEmpty())return Fail(TEXT("unexpected propagation parent"));
        Event.VisibilityTopCm=Event.Kind==EMRDisturbance::Fire||Event.Kind==EMRDisturbance::Smoke?3500.f:
            Event.Kind==EMRDisturbance::LowVisibility?2800.f:1200.f;
        if(Event.Rejection.IsEmpty())
        {
            FVector Source;
            if(!MRCoreJson::Point(Field(Row,TEXT("source")),Source)||!SafePosition(Source,8)||
               Source.Z<-.25||Source.Z>40||
               !OptionalTime(Row,TEXT("expires_at"),Event.Time,Event.ExpiresAt)||
               !OptionalTime(Row,TEXT("visibility_expires_at"),Event.Time,Event.VisibilityExpiresAt))
                return Fail(TEXT("invalid event source or expiry"));
            Event.Source=Source*100;
            const auto& Cells=Row->GetArrayField(TEXT("cells"));
            if(Cells.Num()>256)return Fail(TEXT("event footprint exceeds limit"));
            for(const auto& Pair:Cells)
            {
                if(Pair->Type!=EJson::Array||Pair->AsArray().Num()!=2)return Fail(TEXT("invalid event cell"));
                const auto& XY=Pair->AsArray();
                for(const auto& V:XY)
                    if(V->Type!=EJson::Number||!FMath::IsFinite(V->AsNumber())||V->AsNumber()<0||
                       V->AsNumber()>=Size/5||V->AsNumber()!=FMath::FloorToDouble(V->AsNumber()))
                        return Fail(TEXT("out-of-bounds event cell"));
                const FIntPoint Key(int32(XY[0]->AsNumber()),int32(XY[1]->AsNumber()));
                if(!SafePosition(FMRDistrictEnvironment::Center(Key)/100.,10.5)||Event.Cells.Contains(Key))
                    return Fail(TEXT("duplicate or protected event cell"));
                Event.Cells.Add(Key);
            }
            if(Event.Kind==EMRDisturbance::NewTarget)
            {
                if(!Integer(Row,TEXT("target_id"),Event.TargetId)||ReferencedPeople.Contains(Event.TargetId)||!Event.Cells.IsEmpty())
                    return Fail(TEXT("invalid appearance reference"));
                const auto* Person=LateById.Find(Event.TargetId);
                FVector Position;
                if(!Person||!MRCoreJson::Point(Field(*Person,TEXT("position")),Position)||!Position.Equals(Source,1.e-7)||
                   (*Person)->GetNumberField(TEXT("available_at"))!=Event.Time||Text(*Person,TEXT("appearance_event_id"))!=Event.Id)
                    return Fail(TEXT("appearance is not associated with the late person"));
                ReferencedPeople.Add(Event.TargetId);
            }
            else if(Event.Cells.IsEmpty())return Fail(TEXT("active event has no footprint"));
        }
        Previous=Event.Time;
        const int32 Index=Tape.Add(MoveTemp(Event));
        Earlier.Add(Tape[Index].Id,Index);
    }
    if(ReferencedPeople.Num()!=Late.Num())return Fail(TEXT("unreferenced late person"));
    Scenario->SetArrayField(TEXT("people"),People);
    CoreEventProfile=Profile;
    Environment.Seed=Seed;
    Environment.Horizon=Horizon;
    Environment.Mode=TEXT("core_tape");
    Environment.Tape=MoveTemp(Tape);
    return true;
}

void AMRWorld::ResetCoreEventEffects()
{
    if(CoreEventProfile.IsEmpty())return;
    TSet<USceneComponent*> RuntimeComponents;
    for(USceneComponent* Component:CoreEventComponents)if(Component)RuntimeComponents.Add(Component);
    Generated.RemoveAll([&](const auto& Component){return RuntimeComponents.Contains(Component.Get());});
    for(int32 I=PhysicsPieces.Num()-1;I>=0;--I)
        if(RuntimeComponents.Contains(PhysicsPieces[I]))
        {
            PhysicsPieces.RemoveAt(I);
            if(InitialPiecePositions.IsValidIndex(I))InitialPiecePositions.RemoveAt(I);
        }
    for(int32 I=CoreEventComponents.Num()-1;I>=0;--I)
        if(USceneComponent* Component=CoreEventComponents[I])Component->DestroyComponent();
    CoreEventComponents.Empty();
    HazardVisuals.Empty();
    EventTargetIndices.Empty();
    DustEffect=nullptr;
    FireEffect=nullptr;
    LeakEffect=nullptr;
    FloodGroundHeights.Empty();
    for(auto& Cells:SurfaceCells)Cells.Empty();
    Environment.ResetApplied();
}

int32 AMRWorld::ApplyCoreDisturbance(const FMRDisturbance& Event)
{
    const int32 FirstGenerated=Generated.Num();
    const int32 FirstVisual=HazardVisuals.Num();
    const int32 FirstPiece=PhysicsPieces.Num();
    if(Event.Kind==EMRDisturbance::Collapse)
    {
        // Bound each collapse to a few local convex bodies, released near the
        // facade source. Persistent hazard cells describe the unstable area.
        FRandomStream Rng(FCrc::StrCrc32(*Event.Id)^uint32(Seed));
        for(int32 I=0;I<3;++I)
        {
            const FVector P=Event.Source+FVector(Rng.FRandRange(-90,90),Rng.FRandRange(-90,90),160+I*70);
            auto* Piece=Chunk(Rng,P,I==0?FVector(190,100,30):FVector(70,52,38),true);
            Piece->ComponentTags.Add(FName(*Event.Id));
        }
    }
    if(Event.Kind==EMRDisturbance::NewTarget)
    {
        const int32 Index=Targets.IndexOfByPredicate([&](const auto& T){return T.Id==Event.TargetId;});
        if(Index!=INDEX_NONE)EventTargetIndices.Add(Event.Id,Index);
    }
    ApplyDisturbance(Event);
    for(int32 I=FirstGenerated;I<Generated.Num();++I)CoreEventComponents.Add(Generated[I]);
    for(int32 I=FirstVisual;I<HazardVisuals.Num();++I)CoreEventComponents.AddUnique(HazardVisuals[I]);
    return PhysicsPieces.Num()-FirstPiece;
}

void FMRCoreRuntime::AdvanceEvents()
{
    if(World->CoreEventProfile.IsEmpty())return;
    auto& Model=World->Environment;
    const double Previous=Model.Time;
    for(const auto& Event:Model.Advance(Time()))
    {
        const int32 Bodies=Event.Rejection.IsEmpty()?World->ApplyCoreDisturbance(Event):0;
        Record(Event.Rejection.IsEmpty()?TEXT("environment_event_applied"):TEXT("environment_attempt_rejected"),
            Obj({{TEXT("event_id"),Str(Event.Id)},{TEXT("kind"),Str(MRDisturbanceName(Event.Kind))},
                {TEXT("scheduled_at"),Num(Event.Time)},{TEXT("source_m"),Point(Event.Source/100.)},
                {TEXT("source_object_id"),Event.SiteId.IsEmpty()?Null():Str(Event.SiteId)},
                {TEXT("parent_id"),Event.ParentId.IsEmpty()?Null():Str(Event.ParentId)},{TEXT("cells"),Arr(CellsJson(Event))},
                {TEXT("target_id"),Event.TargetId>=0?Num(Event.TargetId):Null()},
                {TEXT("expires_at"),Model.ActiveUntil(Event)>=0?Num(Model.ActiveUntil(Event)):Null()},
                {TEXT("visibility_expires_at"),Model.VisibilityUntil(Event)>=0?Num(Model.VisibilityUntil(Event)):Null()},
                {TEXT("reason"),Event.Rejection.IsEmpty()?Null():Str(Event.Rejection)},
                {TEXT("released_bodies"),Num(Bodies)}}),false);
        if(CaptureEventFrames&&Event.Rejection.IsEmpty()&&!Event.bPropagation&&!ScheduledViews.Contains(int32(Event.Kind)))
        {
            const bool Flood=Event.Kind==EMRDisturbance::Flood;
            const bool Appearance=Event.Kind==EMRDisturbance::NewTarget;
            ScheduledViews.Add(int32(Event.Kind));
            float Yaw=150;
            if(!Event.SiteId.IsEmpty())
                for(const auto& Item:World->CityLayout->GetArrayField(TEXT("buildings")))
                {
                    const auto Building=Item->AsObject();
                    if(Text(Building,TEXT("id"))!=Event.SiteId)continue;
                    const auto Bounds=Building->GetObjectField(TEXT("bounds"));
                    FVector Low,High;
                    if(MRCoreJson::Point(Field(Bounds,TEXT("min")),Low)&&MRCoreJson::Point(Field(Bounds,TEXT("max")),High))
                        Yaw=float(((Low+High)*50-Event.Source).Rotation().Yaw);
                    break;
                }
            EventViews.Add({Event.Time+(Flood?35.:1.),Event.Source+FVector(0,0,Appearance?65:100),
                FString(MRDisturbanceName(Event.Kind)),Appearance?800.f:2400.f,Yaw});
            EventViews.Sort([](const auto& A,const auto& B){return A.At<B.At;});
        }
    }
    World->TickHazardVisuals(float(ExecutionDelta));
    for(const auto& Event:Model.Applied)
    {
        auto Ended=[&](double At){return At>=0&&Previous+1.e-9<At&&Time()+1.e-9>=At;};
        const bool EndedVisibility=Ended(Model.VisibilityUntil(Event));
        const bool EndedEffect=Ended(Model.ActiveUntil(Event));
        if(EndedVisibility||EndedEffect)
            Record(TEXT("environment_effect_ended"),Obj({{TEXT("event_id"),Str(Event.Id)},
                {TEXT("kind"),Str(MRDisturbanceName(Event.Kind))},{TEXT("visibility_ended"),Bool(EndedVisibility)},
                {TEXT("effect_ended"),Bool(EndedEffect)}}),false);
    }
    UpdateEventView();
}

void FMRCoreRuntime::UpdateEventView()
{
    if(!CaptureEventFrames||EventViews.IsEmpty())return;
    if(ViewStartedAt<0)
    {
        if(Time()<EventViews[0].At)return;
        auto* Camera=Cast<AMRCameraPawn>(UGameplayStatics::GetPlayerPawn(World,0));
        if(!Camera)return;
        const auto& View=EventViews[0];
        Camera->SetInspectionView(View.Focus,View.Distance,View.Yaw,-36);
        ViewStartedAt=Time();
        return;
    }
    if(Time()-ViewStartedAt<.65)return;
    const FString Folder=Directory/TEXT("frames");
    if(!FPlatformFileManager::Get().GetPlatformFile().CreateDirectoryTree(*Folder))
    {
        ArchiveFailure(TEXT("Cannot create native event frame directory"));
        return;
    }
    const FString Name=EventViews[0].Name+TEXT(".png");
    FScreenshotRequest::RequestScreenshot(Folder/Name,false,false);
    Record(TEXT("observer_frame_requested"),Obj({{TEXT("file"),Str(TEXT("frames/")+Name)},
        {TEXT("focus_m"),Point(EventViews[0].Focus/100.)}}),false);
    EventViews.RemoveAt(0);
    ViewStartedAt=-1;
}

float FMRCoreRuntime::SensorQuality(const FVector& Start,const FVector& End) const
{
    if(World->Environment.Applied.IsEmpty())return 1.f;
    const int32 Samples=FMath::Clamp(FMath::CeilToInt(FVector::Dist(Start,End)/250.),1,64);
    float Quality=1.f;
    for(int32 I=0;I<=Samples;++I)
        Quality=FMath::Min(Quality,World->VisibilityQuality(FMath::Lerp(Start,End,double(I)/Samples)));
    return Quality;
}

bool FMRCoreRuntime::SensorAccepts(AMRAgent* Agent,int32 Target,double Quality,int32 Channel) const
{
    const double Probability=FMath::Clamp(Quality*SensorReliability*Agent->SensorFactor,0.,1.);
    if(Probability>=1)return true;
    uint32 Key=HashCombineFast(GetTypeHash(World->Seed),GetTypeHash(Target));
    Key=HashCombineFast(Key,GetTypeHash(Agent->AgentId*2+int32(Agent->bAerial)));
    Key=HashCombineFast(Key,GetTypeHash(int64(FMath::RoundToDouble(Time()*1.e6))));
    FRandomStream Sensor(HashCombineFast(Key,GetTypeHash(Channel)));
    return Sensor.FRand()<Probability;
}

void FMRCoreRuntime::GatherHazardReport(AMRAgent* Agent)
{
    const auto& Environment=World->Environment;
    if(World->CoreEventProfile.IsEmpty()||Environment.Applied.IsEmpty())return;
    const FString Id=Agent->AgentKey();
    const FVector Pose=Agent->GetActorLocation();
    const double Range=100*SensorRadius.FindRef(Id);
    const auto Origin=FMRDistrictEnvironment::Cell(Pose);
    const int32 Radius=FMath::CeilToInt(Range/MRDistrictSettings::CellCm);
    const int32 MaxCell=2*World->GridSize;
    TArray<Value> Readings;
    FCollisionQueryParams Query(SCENE_QUERY_STAT(MRCoreHazardObservation),false);
    Query.AddIgnoredActor(Agent);
    for(int32 X=FMath::Max(0,Origin.X-Radius);X<FMath::Min(MaxCell,Origin.X+Radius+1);++X)
        for(int32 Y=FMath::Max(0,Origin.Y-Radius);Y<FMath::Min(MaxCell,Origin.Y+Radius+1);++Y)
        {
            const FIntPoint Cell(X,Y);
            if(!Environment.HasHistoryAt(Cell))continue;
            const FVector Position=FMRDistrictEnvironment::Center(Cell);
            if(FVector::DistSquared2D(Pose,Position)>FMath::Square(Range))continue;
            const FString ZoneId=FString::Printf(TEXT("surface-%d-%d"),X,Y);
            TArray<Value> Types;
            for(EMRDisturbance Kind:{EMRDisturbance::Collapse,EMRDisturbance::Fire,EMRDisturbance::Flood,
                EMRDisturbance::Mud,EMRDisturbance::RoadDamage,EMRDisturbance::Smoke,EMRDisturbance::LowVisibility})
                if(Environment.HasEffect(Kind,Position))Types.Add(Str(MRDisturbanceName(Kind)));
            const float Visibility=World->VisibilityQuality(Position+FVector(0,0,60));
            const double WaterCm=World->WaterDepth(Position);
            const bool Blocked=World->IsUnsafeGround(Position);
            const double Cost=FMath::Max(Environment.Cost(Position,false),WaterCm>4?2.f:1.f);
            const bool Active=!Types.IsEmpty()||Visibility<1||Blocked||Cost>1;
            const auto* Known=KnownZones.Find(ZoneId);
            if(!Active&&!Known)continue;
            const auto Measurement=Obj({{TEXT("kinds"),Arr(Types)},{TEXT("active"),Bool(Active)},
                {TEXT("ground_blocked"),Bool(Blocked)},{TEXT("surface_multiplier"),Num(Cost)},
                {TEXT("depth_m"),Num(FMath::FloorToDouble(WaterCm)/100.)},{TEXT("visibility"),Num(Visibility)}});
            if(Known&&Time()-SurfaceObservedAt.FindRef(ZoneId)<4&&
               MRCoreJson::Equal(Field(*Known,TEXT("surface")),Json(Measurement)))continue;
            if(World->GetWorld()->LineTraceTestByChannel(Pose,Position+FVector(0,0,65),ECC_Visibility,Query))continue;
            Readings.Add(Json(Obj({{TEXT("id"),Str(ZoneId)},{TEXT("cell"),Arr({Num(X),Num(Y)})},
                {TEXT("surface"),Json(Measurement)}})));
        }
    if(Readings.IsEmpty())return;
    FReport Packet;
    Packet.Agent=Id;
    Packet.MessageId=FGuid::NewGuid().ToString(EGuidFormats::Digits);
    Packet.Kind=EPacket::Hazard;
    Packet.Sequence=SensorSamples;
    Packet.Data=Obj({{TEXT("message_id"),Str(Packet.MessageId)},{TEXT("source_id"),Str(Id)},
        {TEXT("observed_at"),Num(Time())},{TEXT("readings"),Arr(Readings)}});
    Record(TEXT("hazard_observation"),Packet.Data,false);
    QueueReport(MoveTemp(Packet));
}

void FMRCoreRuntime::DeliverHazardReport(const FReport& Packet)
{
    const double ObservedAt=Packet.Data->GetNumberField(TEXT("observed_at"));
    TArray<Value> Delivered;
    for(const auto& Item:Packet.Data->GetArrayField(TEXT("readings")))
    {
        const auto Reading=Item->AsObject();
        const FString Id=Text(Reading,TEXT("id"));
        const double* PreviousAt=SurfaceObservedAt.Find(Id);
        if(PreviousAt&&*PreviousAt>=ObservedAt)continue;
        const auto Measured=Reading->GetObjectField(TEXT("surface"));
        const bool Active=Measured->GetBoolField(TEXT("active"));
        const bool Blocked=Measured->GetBoolField(TEXT("ground_blocked"));
        const auto* Previous=KnownZones.Find(Id);
        if(!Active&&!Previous)continue;
        const bool WasBlocked=Previous&&(*Previous)->GetObjectField(TEXT("surface"))->GetBoolField(TEXT("ground_blocked"));
        const bool Changed=!Previous||!MRCoreJson::Equal(Field(*Previous,TEXT("surface")),Json(Measured));
        SurfaceObservedAt.Add(Id,ObservedAt);
        const auto& Cell=Reading->GetArrayField(TEXT("cell"));
        const double X=Cell[0]->AsNumber()*5,Y=Cell[1]->AsNumber()*5;
        if(Active)
        {
            const bool Wet=Measured->GetNumberField(TEXT("depth_m"))>0;
            auto Geometry=Obj({{TEXT("type"),Str(TEXT("box"))},{TEXT("min"),Point(FVector(X,Y,-.15))},
                {TEXT("max"),Point(FVector(X+5,Y+5,1.2))}});
            KnownZones.Add(Id,Obj({{TEXT("id"),Str(Id)},{TEXT("geometry"),Json(Geometry)},
                {TEXT("type"),Str(Wet?TEXT("water"):TEXT("hazard"))},
                {TEXT("access"),Json(Obj({{TEXT("allowed_kinds"),Blocked?Strings({TEXT("aerial")}):Strings({TEXT("ground"),TEXT("aerial")})}}))},
                {TEXT("risk"),Num(Blocked?1:1-Measured->GetNumberField(TEXT("visibility")))},
                {TEXT("cost"),Json(Obj({{TEXT("energy_multiplier"),Field(Measured,TEXT("surface_multiplier"))}}))},
                {TEXT("communication"),Json(Obj())},{TEXT("constraints"),Arr({})},
                {TEXT("observed_at"),Num(ObservedAt)},{TEXT("received_at"),Num(Time())},{TEXT("source_id"),Str(Packet.Agent)},
                {TEXT("message_id"),Str(Packet.MessageId)},{TEXT("surface"),Json(Measured)}}));
        }
        else KnownZones.Remove(Id);
        auto PublicReading=MRCoreJson::Copy(Reading);
        PublicReading->SetNumberField(TEXT("observed_at"),ObservedAt);
        Delivered.Add(Json(PublicReading));
        if(Changed)
        {
            const FString EventType=Active&&Blocked&&!WasBlocked?TEXT("hazard_appeared"):TEXT("environment_change");
            auto Details=MRCoreJson::Copy(Measured);Details->SetStringField(TEXT("message_id"),Packet.MessageId);
            PublishEvent(Packet.MessageId+TEXT("-")+Id,EventType,ObservedAt,Packet.Agent,{Id},Details,
                Active?TEXT("active"):TEXT("resolved"));
        }
    }
    if(!Delivered.IsEmpty())Record(TEXT("hazard_report_delivered"),Obj({{TEXT("message_id"),Str(Packet.MessageId)},
        {TEXT("source_id"),Str(Packet.Agent)},{TEXT("observed_at"),Num(ObservedAt)},{TEXT("received_at"),Num(Time())},
        {TEXT("readings"),Arr(Delivered)}}));
}
