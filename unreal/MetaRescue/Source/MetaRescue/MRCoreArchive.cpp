#include "MRCoreRuntime.h"
#include "MRCoreReset.h"
#include "MRCoreJson.h"
#include "MRCoreValues.h"
#include "MRWorld.h"
#include "MRAgent.h"
#include "ProceduralMeshComponent.h"
#include "Misc/Base64.h"
#include "Misc/FileHelper.h"
#include "Misc/SecureHash.h"
#include "HAL/FileManager.h"
#include "Serialization/JsonSerializer.h"

using namespace MRCoreValues;

FString FMRCoreRuntime::ReplayKey(const FString& Id)
{
    const FTCHARToUTF8 Bytes(*Id);return FSHA1::HashBuffer(Bytes.Get(),Bytes.Length()).ToString();
}

void FMRCoreRuntime::ArchiveFailure(const FString& Message)
{
    if(StorageError.IsEmpty()){StorageError=Message;UE_LOG(LogTemp,Error,TEXT("MR_CORE archive incomplete: %s"),*Message);}
    Status=TEXT("failed");OutcomeReason=TEXT("archive_io_failed");
    // A manifest failure can happen after FinishStep built its public snapshot.
    // Publish the terminal outcome immediately; GET must not advertise running.
    if(CachedObservation&&Text(CachedObservation,TEXT("episode_id"))==Episode)
        Snapshot(Text(CachedObservation,TEXT("request_id")));
}

bool FMRCoreRuntime::LoadReplay(const FString& Id,FReplay& Replay,bool& Found)
{
    const int64* Index=ReplayKeys.Find(ReplayKey(Id));Found=Index!=nullptr;if(!Found)return true;
    FString Error;TArray<uint8> Raw;
    if(!ReplayJournal||!ReplayJournal->Read(*Index,Raw,Error)){ArchiveFailure(Error);return false;}
    const FUTF8ToTCHAR TextBytes(reinterpret_cast<const ANSICHAR*>(Raw.GetData()),Raw.Num());
    Object Data;
    if(!FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(FString(TextBytes.Length(),TextBytes.Get())),Data)||!Data||
       Text(Data,TEXT("decision_id"))!=Id||!Is(Data,TEXT("response"),EJson::String)||!Is(Data,TEXT("http_status"),EJson::Number)||
       !FBase64::Decode(Text(Data,TEXT("request_body_base64")),Replay.Body))
    {ArchiveFailure(TEXT("Corrupt replay record or digest collision"));return false;}
    Replay.Response=Text(Data,TEXT("response"));Replay.HttpStatus=int32(Data->GetNumberField(TEXT("http_status")));
    if(Replay.HttpStatus<100||Replay.HttpStatus>599){ArchiveFailure(TEXT("Corrupt replay HTTP status"));return false;}
    return true;
}

bool FMRCoreRuntime::StoreReplay(const FString& Id,const FReplay& Replay)
{
    auto Data=Obj({{TEXT("decision_id"),Str(Id)},{TEXT("request_body_base64"),Str(FBase64::Encode(Replay.Body))},
        {TEXT("response"),Str(Replay.Response)},{TEXT("http_status"),Num(Replay.HttpStatus)}});
    const FString Serialized=MRCoreJson::Write(Data);const FTCHARToUTF8 Bytes(*Serialized);
    TArray<uint8> Raw;Raw.Append(reinterpret_cast<const uint8*>(Bytes.Get()),Bytes.Length());FString Error;
    if(!ReplayJournal||!ReplayJournal->Append(Raw,Error)){ArchiveFailure(Error);return false;}
    ReplayKeys.Add(ReplayKey(Id),ReplayJournal->Num()-1);return true;
}

bool FMRCoreRuntime::FlushArchive()
{
    FString Error;
    for(auto* Journal:{PublicJournal.Get(),TruthJournal.Get(),ReplayJournal.Get()})
        if(Journal&&!Journal->Flush(Error)){ArchiveFailure(Error);return false;}
    return true;
}

void FMRCoreRuntime::ArchiveManifest(const FString& State)
{
    if(Directory.IsEmpty())return;
    auto Files=Obj();
    auto Add=[&](const FString& Name,const FMRCoreDiskRecords* Journal)
    {
        if(Journal)Files->SetObjectField(Name,Obj({{TEXT("records"),Num(Journal->Num())},
            {TEXT("stored_bytes"),Num(Journal->Bytes())},{TEXT("uncompressed_bytes"),Num(Journal->UncompressedBytes())},
            {TEXT("index_bytes"),Num(Journal->Num()*24)}}));
    };
    Add(TEXT("public"),PublicJournal.Get());Add(TEXT("truth"),TruthJournal.Get());Add(TEXT("replay"),ReplayJournal.Get());
    int32 LocalDigests=0;for(AMRAgent* A:World->Agents)LocalDigests+=A->PendingCommandDigestCount();
    auto Manifest=Obj({{TEXT("format"),Str(TEXT("metarescue.indexed-json.v1"))},{TEXT("episode_id"),Str(Episode)},
        {TEXT("state"),Str(StorageError.IsEmpty()?State:TEXT("incomplete"))},{TEXT("status"),Str(Status)},
        {TEXT("time"),Num(Time())},{TEXT("world_seed"),Num(World->Seed)},
        {TEXT("generated_layout"),ResetState&&!ResetState->LayoutFile.IsEmpty()?Str(ResetState->LayoutFile):Null()},
        {TEXT("error"),StorageError.IsEmpty()?Null():Str(StorageError)},
        {TEXT("files"),Json(Files)},{TEXT("replay_index_entries"),Num(ReplayKeys.Num())},
        {TEXT("live_command_states"),Num(Commands.Num())},{TEXT("agent_command_digests"),Num(LocalDigests)}});
    const FString Pending=Directory/TEXT("manifest.json.part"),Final=Directory/TEXT("manifest.json");
    if(!FFileHelper::SaveStringToFile(MRCoreJson::Write(Manifest),*Pending,FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM)||
       !IFileManager::Get().Move(*Final,*Pending,true,false,false,true))
        ArchiveFailure(TEXT("Cannot save archive manifest"));
}

void FMRCoreRuntime::RecordTruthSnapshot(const FString& Phase)
{
    TArray<Value> Agents,Targets,Pieces;
    for(AMRAgent* A:World->Agents)Agents.Add(Json(AgentSnapshot(A,Time())));
    for(int32 Index=0;Index<World->Targets.Num();Index++)
    {
        const auto& T=World->Targets[Index];
        Targets.Add(Json(Obj({{TEXT("id"),Str(FString::Printf(TEXT("person-%d"),T.Id))},
            {TEXT("position"),Point((T.Visual?T.Visual->GetActorLocation():T.Position)/100.)},
            {TEXT("available_at"),Num(T.AvailableAt)},{TEXT("discovered"),Bool(T.bDiscovered)},
            {TEXT("visible"),Bool(T.Visual&&!T.Visual->IsHidden())},
            {TEXT("assigned"),Bool(T.bAssigned)},{TEXT("rescued"),Bool(T.bRescued)},
            {TEXT("priority"),Num(T.Priority)},{TEXT("aid_received"),Num(ReceivedKits.FindRef(Index))}})));
    }
    for(UProceduralMeshComponent* P:World->PhysicsPieces)if(P)
        Pieces.Add(Json(Obj({{TEXT("id"),Str(P->GetName())},{TEXT("position"),Point(P->GetComponentLocation()/100.)},
            {TEXT("rotation_degrees"),Point(FVector(P->GetComponentRotation().Roll,P->GetComponentRotation().Pitch,P->GetComponentRotation().Yaw))},
            {TEXT("velocity_m_s"),Point(P->GetPhysicsLinearVelocity()/100.)},{TEXT("simulating"),Bool(P->IsSimulatingPhysics())}})));
    Record(TEXT("truth_snapshot"),Obj({{TEXT("format"),Str(TEXT("metarescue.truth-snapshot.v1"))},{TEXT("phase"),Str(Phase)},
        {TEXT("agents"),Arr(Agents)},{TEXT("targets"),Arr(Targets)},{TEXT("physics_pieces"),Arr(Pieces)},
        {TEXT("environment_revision"),Num(World->Environment.Revision)},{TEXT("applied_events"),Num(World->Environment.Applied.Num())}}),false);
}
