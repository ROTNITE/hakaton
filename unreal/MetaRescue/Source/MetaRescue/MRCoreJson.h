#pragma once
#include "CoreMinimal.h"
#include "Dom/JsonObject.h"

// The wire parser rejects ambiguity before the engine DOM can overwrite keys.
namespace MRCoreJson
{
    bool Parse(const TArray<uint8>& Bytes,TSharedPtr<FJsonObject>& Object,FString& Error);
    FString Write(const TSharedPtr<FJsonObject>& Object);
    TSharedPtr<FJsonObject> Copy(const TSharedPtr<FJsonObject>& Object);
    bool Equal(const TSharedPtr<FJsonValue>& A,const TSharedPtr<FJsonValue>& B);
    bool Point(const TSharedPtr<FJsonValue>& Value,FVector& Metres);
}
