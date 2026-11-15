#pragma once
#include "Dom/JsonObject.h"

namespace MRCoreExpressions
{
// Missing values are an invalid shared pointer. JSON null remains a value.
bool Validate(const TSharedPtr<FJsonObject>& Expression,bool ExecutionScope=false);
TSharedPtr<FJsonValue> Evaluate(const TSharedPtr<FJsonObject>& Expression,const TSharedPtr<FJsonObject>& Context);
}
