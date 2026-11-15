#pragma once

#include "CoreMinimal.h"
#include "Dom/JsonObject.h"
#include "HttpResultCallback.h"

struct FMRCoreResetOperation
{
    TSharedPtr<FJsonObject> Request;
    TArray<uint8> Body;
    TArray<FHttpResultCallback> Callbacks;
    bool TravelScheduled=false;
};

// Persists across replacement of the game world in the same environment process.
struct FMRCoreResetState
{
    int32 StartupSeed=INDEX_NONE;
    bool GenerateEvents=false, Customized=false;
    TSharedPtr<FJsonObject> Defaults;
    FString LayoutFile;
    TSet<FString> AcceptedIds;
    FString LastId,LastResponse;
    TArray<uint8> LastBody;
    TOptional<FMRCoreResetOperation> Pending;
};
