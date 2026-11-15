#include "MRCoreJson.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#if WITH_DEV_AUTOMATION_TESTS
#include "Misc/AutomationTest.h"
#endif

namespace
{
bool Unicode(const FString& Text)
{
    for(int32 I=0;I<Text.Len();I++)
    {
        const uint32 C=uint32(Text[I]);
        if(C>=0xd800&&C<=0xdbff)
        {
            if(sizeof(TCHAR)!=2||++I>=Text.Len()||uint32(Text[I])<0xdc00||uint32(Text[I])>0xdfff)return false;
        }
        else if((C>=0xdc00&&C<=0xdfff)||C>0x10ffff)return false;
    }
    return true;
}
}

bool MRCoreJson::Parse(const TArray<uint8>& Bytes,TSharedPtr<FJsonObject>& Object,FString& Error)
{
    Object.Reset();
    if(Bytes.IsEmpty()||Bytes.Num()>2*1024*1024){Error=TEXT("JSON request must be 1..2097152 bytes");return false;}
    const FUTF8ToTCHAR Converted(reinterpret_cast<const ANSICHAR*>(Bytes.GetData()),Bytes.Num());
    const FString Text(Converted.Length(),Converted.Get());
    const FTCHARToUTF8 Roundtrip(*Text,Text.Len());
    if(Roundtrip.Length()!=Bytes.Num()||FMemory::Memcmp(Roundtrip.Get(),Bytes.GetData(),Bytes.Num())!=0||!Unicode(Text))
    {Error=TEXT("Invalid UTF-8");return false;}
    struct FFrame {bool Object=false;TSet<FString> Keys;};
    TArray<FFrame> Stack;
    auto Reader=TJsonReaderFactory<>::Create(Text);EJsonNotation Token;
    while(Reader->ReadNext(Token))
    {
        if(Token==EJsonNotation::Error){Error=TEXT("Malformed JSON");return false;}
        if(Token==EJsonNotation::ObjectEnd||Token==EJsonNotation::ArrayEnd)
        {if(Stack.IsEmpty()){Error=TEXT("Unbalanced JSON");return false;}Stack.Pop();continue;}
        const FString& Key=Reader->GetIdentifier();
        if(!Unicode(Key)){Error=TEXT("Invalid Unicode key");return false;}
        if(!Stack.IsEmpty()&&Stack.Last().Object)
        {
            if(Stack.Last().Keys.Contains(Key)){Error=TEXT("Duplicate JSON key");return false;}
            Stack.Last().Keys.Add(Key);
        }
        if(Token==EJsonNotation::String&&!Unicode(Reader->GetValueAsString()))
        {Error=TEXT("Invalid Unicode value");return false;}
        if(Token==EJsonNotation::Number&&!FMath::IsFinite(Reader->GetValueAsNumber()))
        {Error=TEXT("Non-finite number");return false;}
        if(Token==EJsonNotation::ObjectStart||Token==EJsonNotation::ArrayStart)
        {
            if(Stack.Num()>=64){Error=TEXT("JSON nesting exceeds 64");return false;}
            FFrame Frame;Frame.Object=Token==EJsonNotation::ObjectStart;Stack.Add(MoveTemp(Frame));
        }
    }
    if(!Reader->GetErrorMessage().IsEmpty()||!Stack.IsEmpty()||
       !FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text),Object)||!Object)
    {Error=TEXT("Expected one JSON object");return false;}
    return true;
}

FString MRCoreJson::Write(const TSharedPtr<FJsonObject>& Object)
{
    FString Result;
    FJsonSerializer::Serialize(Object.ToSharedRef(),TJsonWriterFactory<TCHAR,TCondensedJsonPrintPolicy<TCHAR>>::Create(&Result));
    return Result;
}

TSharedPtr<FJsonObject> MRCoreJson::Copy(const TSharedPtr<FJsonObject>& Object)
{
    TSharedPtr<FJsonObject> Result;
    FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Write(Object)),Result);
    return Result;
}

bool MRCoreJson::Equal(const TSharedPtr<FJsonValue>& A,const TSharedPtr<FJsonValue>& B)
{
    if(!A||!B||A->Type!=B->Type)return false;
    if(A->Type==EJson::Null)return true;
    if(A->Type==EJson::String)return A->AsString()==B->AsString();
    if(A->Type==EJson::Number)return A->AsNumber()==B->AsNumber();
    if(A->Type==EJson::Boolean)return A->AsBool()==B->AsBool();
    if(A->Type==EJson::Array)
    {
        const auto& X=A->AsArray();const auto& Y=B->AsArray();if(X.Num()!=Y.Num())return false;
        for(int32 I=0;I<X.Num();I++)if(!Equal(X[I],Y[I]))return false;
        return true;
    }
    if(A->Type==EJson::Object)
    {
        const auto& X=A->AsObject()->Values;const auto& Y=B->AsObject()->Values;
        if(X.Num()!=Y.Num())return false;
        for(const auto& Pair:X){const auto* Other=Y.Find(Pair.Key);if(!Other||!Equal(Pair.Value,*Other))return false;}
        return true;
    }
    return false;
}

bool MRCoreJson::Point(const TSharedPtr<FJsonValue>& Value,FVector& Metres)
{
    if(!Value||Value->Type!=EJson::Array||Value->AsArray().Num()!=3)return false;
    const auto& A=Value->AsArray();
    for(int32 I=0;I<3;I++)if(A[I]->Type!=EJson::Number||!FMath::IsFinite(A[I]->AsNumber()))return false;
    Metres=FVector(A[0]->AsNumber(),A[1]->AsNumber(),A[2]->AsNumber());return true;
}

#if WITH_DEV_AUTOMATION_TESTS
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMRCoreJsonTest,"MetaRescue.Core.StrictWire",EAutomationTestFlags::EditorContext|EAutomationTestFlags::EngineFilter)
bool FMRCoreJsonTest::RunTest(const FString&)
{
    auto Parse=[](const FString& Text)
    {FTCHARToUTF8 Utf8(*Text);TArray<uint8> Bytes;Bytes.Append(reinterpret_cast<const uint8*>(Utf8.Get()),Utf8.Length());TSharedPtr<FJsonObject> J;FString E;return MRCoreJson::Parse(Bytes,J,E);};
    TestTrue(TEXT("nested distinct key scopes"),Parse(TEXT("{\"a\":{\"x\":1},\"b\":[{\"x\":2}]}")));
    TestFalse(TEXT("duplicate decoded key"),Parse(TEXT("{\"x\":1,\"\\u0078\":2}")));
    TestFalse(TEXT("nested duplicate"),Parse(TEXT("{\"a\":[{\"x\":1,\"x\":2}]}")));
    TestFalse(TEXT("nonfinite exponent"),Parse(TEXT("{\"x\":1e999}")));
    TestFalse(TEXT("unpaired escaped surrogate"),Parse(TEXT("{\"x\":\"\\ud800\"}")));
    TestTrue(TEXT("valid surrogate pair"),Parse(TEXT("{\"x\":\"\\ud83d\\ude80\"}")));
    TestFalse(TEXT("trailing second object"),Parse(TEXT("{}{}")));
    TestFalse(TEXT("invalid UTF8"),[&](){TArray<uint8>B={123,34,120,34,58,34,0xc0,0xaf,34,125};TSharedPtr<FJsonObject>J;FString E;return MRCoreJson::Parse(B,J,E);}());
    FVector P;
    TestFalse(TEXT("boolean is not point number"),MRCoreJson::Point(MakeShared<FJsonValueArray>(TArray<TSharedPtr<FJsonValue>>{MakeShared<FJsonValueBoolean>(true),MakeShared<FJsonValueNumber>(0),MakeShared<FJsonValueNumber>(0)}),P));
    return true;
}
#endif
