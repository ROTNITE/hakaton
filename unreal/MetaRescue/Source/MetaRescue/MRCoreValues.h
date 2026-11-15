#pragma once
#include "Dom/JsonObject.h"
#include <initializer_list>

namespace MRCoreValues
{
using Object=TSharedPtr<FJsonObject>;
using Value=TSharedPtr<FJsonValue>;
inline Value Str(const FString& S){return MakeShared<FJsonValueString>(S);}
inline Value Num(double N){return MakeShared<FJsonValueNumber>(N);}
inline Value Bool(bool B){return MakeShared<FJsonValueBoolean>(B);}
inline Value Null(){return MakeShared<FJsonValueNull>();}
inline Value Json(const Object& O){return MakeShared<FJsonValueObject>(O);}
inline Value Arr(const TArray<Value>& A){return MakeShared<FJsonValueArray>(A);}
inline Object Obj(std::initializer_list<TPair<FString,Value>> Fields={})
{auto O=MakeShared<FJsonObject>();for(const auto& P:Fields)O->SetField(P.Key,P.Value);return O;}
inline Value Strings(std::initializer_list<FString> Items)
{TArray<Value>A;for(const auto& S:Items)A.Add(Str(S));return Arr(A);}
inline Value Point(FVector Metres){return Arr({Num(Metres.X),Num(Metres.Y),Num(Metres.Z)});}
inline Value Field(const Object& O,const FString& Key){return O?O->TryGetField(Key):nullptr;}
inline bool Is(const Object& O,const FString& Key,EJson Type){auto V=Field(O,Key);return V&&V->Type==Type;}
inline FString Text(const Object& O,const FString& Key){auto V=Field(O,Key);return V&&V->Type==EJson::String?V->AsString():FString();}
inline Value Resource(const FString& Id,double Value)
{return Json(Obj({{TEXT("id"),Str(Id)},{TEXT("value"),Num(FMath::Clamp(Value,0.,1.))},{TEXT("minimum"),Num(0)},
{TEXT("maximum"),Num(1)},{TEXT("unit"),Str(TEXT("normalized"))}}));}
}
