#include "MRCoreExpressions.h"
#include "MRCoreJson.h"
#include "MRCoreValues.h"

using namespace MRCoreValues;

namespace
{
enum class EType:uint8 {Unknown,Boolean,Number,String,Array,Other,Invalid};

bool Fields(const Object& Node,std::initializer_list<FString> Required,std::initializer_list<FString> Optional={})
{
    TSet<FString> Allowed;
    for(const FString& Key:Required){if(!Node->HasField(Key))return false;Allowed.Add(Key);}
    for(const FString& Key:Optional)Allowed.Add(Key);
    for(const auto& Item:Node->Values)if(!Allowed.Contains(FString(*Item.Key)))return false;
    return true;
}

bool Name(const FString& Text)
{
    if(Text.IsEmpty()||(!FChar::IsAlpha(Text[0])&&Text[0]!=TEXT('_')))return false;
    for(TCHAR Char:Text)if(!FChar::IsAlnum(Char)&&Char!=TEXT('_'))return false;
    return true;
}

EType LiteralType(const Value& Value)
{
    if(!Value)return EType::Invalid;
    if(Value->Type==EJson::Boolean)return EType::Boolean;
    if(Value->Type==EJson::Number)return EType::Number;
    if(Value->Type==EJson::String)return EType::String;
    if(Value->Type==EJson::Array)return EType::Array;
    return EType::Other;
}

bool IsType(EType Value,EType Expected){return Value==Expected||Value==EType::Unknown;}

EType Check(const Value& Value,TSet<FString> Variables,const TSet<FString>& Roots,int32 Depth,int32& Budget)
{
    if(!Value||Value->Type!=EJson::Object||++Budget>256||Depth>16)return EType::Invalid;
    const auto Node=Value->AsObject();
    if(Node->HasField(TEXT("value")))return Fields(Node,{TEXT("value")})?LiteralType(Field(Node,TEXT("value"))):EType::Invalid;
    if(Node->HasField(TEXT("path")))
    {
        const FString Path=Text(Node,TEXT("path"));TArray<FString> Parts;Path.ParseIntoArray(Parts,TEXT("."),false);
        if(!Fields(Node,{TEXT("path")})||Parts.IsEmpty()||Path.Len()>1024)return EType::Invalid;
        if(Parts[0].StartsWith(TEXT("$")))
        {if(!Variables.Contains(Parts[0].Mid(1)))return EType::Invalid;}
        else if(!Roots.Contains(Parts[0]))return EType::Invalid;
        for(int32 I=0;I<Parts.Num();I++)
        {
            const FString Part=I==0&&Parts[I].StartsWith(TEXT("$"))?Parts[I].Mid(1):Parts[I];
            if(!Name(Part)&&!Part.IsNumeric())return EType::Invalid;
            if(I>0&&Part.Contains(TEXT("$")))return EType::Invalid;
        }
        return EType::Unknown;
    }
    const FString Op=Text(Node,TEXT("op"));
    const auto Child=[&](const FString& Key){return Check(Field(Node,Key),Variables,Roots,Depth+1,Budget);};
    if(Op==TEXT("and")||Op==TEXT("or"))
    {
        if(!Fields(Node,{TEXT("op"),TEXT("args")})||!Is(Node,TEXT("args"),EJson::Array))return EType::Invalid;
        for(const auto& ChildValue:Node->GetArrayField(TEXT("args")))
            if(!IsType(Check(ChildValue,Variables,Roots,Depth+1,Budget),EType::Boolean))return EType::Invalid;
    }
    else if(Op==TEXT("not")||Op==TEXT("exists"))
    {
        if(!Fields(Node,{TEXT("op"),TEXT("arg")}))return EType::Invalid;
        if(Op==TEXT("exists"))
        {
            const auto Arg=Field(Node,TEXT("arg"));
            if(!Arg||Arg->Type!=EJson::Object||!Is(Arg->AsObject(),TEXT("path"),EJson::String)||Child(TEXT("arg"))==EType::Invalid)
                return EType::Invalid;
        }
        else if(!IsType(Child(TEXT("arg")),EType::Boolean))return EType::Invalid;
    }
    else if(Op==TEXT("all")||Op==TEXT("any")||Op==TEXT("count")||Op==TEXT("sum"))
    {
        const FString Variable=Text(Node,TEXT("var"));
        if(!Name(Variable)||!IsType(Child(TEXT("items")),EType::Array))return EType::Invalid;
        if(Op==TEXT("count"))
        {if(!Fields(Node,{TEXT("op"),TEXT("items"),TEXT("var")},{TEXT("where")}))return EType::Invalid;}
        else if(!Fields(Node,{TEXT("op"),TEXT("items"),TEXT("var"),Op==TEXT("sum")?TEXT("select"):TEXT("where")}))return EType::Invalid;
        Variables.Add(Variable);
        if(Node->HasField(TEXT("where"))&&!IsType(Check(Field(Node,TEXT("where")),Variables,Roots,Depth+1,Budget),EType::Boolean))
            return EType::Invalid;
        if(Op==TEXT("sum")&&!IsType(Check(Field(Node,TEXT("select")),Variables,Roots,Depth+1,Budget),EType::Number))
            return EType::Invalid;
        if(Op==TEXT("count")||Op==TEXT("sum"))return EType::Number;
    }
    else
    {
        if(!Fields(Node,{TEXT("op"),TEXT("left"),TEXT("right")}))return EType::Invalid;
        const EType Left=Child(TEXT("left")),Right=Child(TEXT("right"));
        if(Left==EType::Invalid||Right==EType::Invalid)return EType::Invalid;
        if(Op==TEXT("eq")||Op==TEXT("ne"))
        {
            if((Left==EType::Boolean&&Right==EType::Number)||(Left==EType::Number&&Right==EType::Boolean))return EType::Invalid;
        }
        else if(Op==TEXT("in")){if(!IsType(Right,EType::Array))return EType::Invalid;}
        else if(Op==TEXT("lt")||Op==TEXT("le")||Op==TEXT("gt")||Op==TEXT("ge"))
        {if(!IsType(Left,EType::Number)||!IsType(Right,EType::Number))return EType::Invalid;}
        else return EType::Invalid;
    }
    return EType::Boolean;
}

Value Resolve(const FString& Path,const Object& Context,const TMap<FString,Value>& Variables)
{
    TArray<FString> Parts;Path.ParseIntoArray(Parts,TEXT("."),false);
    Value Current=Json(Context);int32 Index=0;
    if(Parts[0].StartsWith(TEXT("$"))){Current=Variables.FindRef(Parts[0].Mid(1));Index=1;}
    for(;Index<Parts.Num();++Index)
    {
        if(!Current)return nullptr;
        if(Current->Type==EJson::Object)Current=Field(Current->AsObject(),Parts[Index]);
        else if(Current->Type==EJson::Array)
        {
            if(!Parts[Index].IsNumeric())return nullptr;
            const int64 Item=FCString::Atoi64(*Parts[Index]);
            if(Item<0||Item>=Current->AsArray().Num())return nullptr;
            Current=Current->AsArray()[int32(Item)];
        }
        else return nullptr;
    }
    return Current;
}

Value Run(const Object& Node,const Object& Context,TMap<FString,Value> Variables,int32& Work)
{
    if(!Node||++Work>100000)return nullptr;
    if(auto Literal=Field(Node,TEXT("value")))return Literal;
    if(Is(Node,TEXT("path"),EJson::String))return Resolve(Text(Node,TEXT("path")),Context,Variables);
    const FString Op=Text(Node,TEXT("op"));
    const auto Child=[&](const FString& Key){return Run(Node->GetObjectField(Key),Context,Variables,Work);};
    if(Op==TEXT("and")||Op==TEXT("or"))
    {
        bool Unknown=false;
        for(const auto& V:Node->GetArrayField(TEXT("args")))
        {
            const auto Result=Run(V->AsObject(),Context,Variables,Work);
            if(!Result){Unknown=true;continue;}
            if(Result->Type!=EJson::Boolean)return nullptr;
            if(Result->AsBool()==(Op==TEXT("or")))return Bool(Result->AsBool());
        }
        return Unknown?nullptr:Bool(Op==TEXT("and"));
    }
    if(Op==TEXT("not")||Op==TEXT("exists"))
    {
        const auto Result=Child(TEXT("arg"));
        if(Op==TEXT("exists"))return Bool(Result.IsValid());
        return Result&&Result->Type==EJson::Boolean?Bool(!Result->AsBool()):nullptr;
    }
    if(Op==TEXT("all")||Op==TEXT("any")||Op==TEXT("count")||Op==TEXT("sum"))
    {
        const auto Items=Child(TEXT("items"));
        if(!Items||Items->Type!=EJson::Array||Items->AsArray().Num()>20000)return nullptr;
        bool Unknown=false;double Total=0;
        for(const auto& Item:Items->AsArray())
        {
            Variables.Add(Text(Node,TEXT("var")),Item);
            const auto Result=Op==TEXT("sum")?Child(TEXT("select")):Node->HasField(TEXT("where"))?Child(TEXT("where")):Bool(true);
            if(!Result){Unknown=true;continue;}
            if(Op==TEXT("sum"))
            {
                if(Result->Type!=EJson::Number)return nullptr;
                Total+=Result->AsNumber();if(!FMath::IsFinite(Total))return nullptr;
            }
            else
            {
                if(Result->Type!=EJson::Boolean)return nullptr;
                if(Op==TEXT("all")&&!Result->AsBool())return Bool(false);
                if(Op==TEXT("any")&&Result->AsBool())return Bool(true);
                if(Op==TEXT("count")&&Result->AsBool())Total+=1;
            }
        }
        if(Unknown)return nullptr;
        return Op==TEXT("sum")||Op==TEXT("count")?Num(Total):Bool(Op==TEXT("all"));
    }
    const auto Left=Child(TEXT("left")),Right=Child(TEXT("right"));
    if(!Left||!Right)return nullptr;
    if(Op==TEXT("eq")||Op==TEXT("ne"))
    {
        if((Left->Type==EJson::Boolean&&Right->Type==EJson::Number)||(Left->Type==EJson::Number&&Right->Type==EJson::Boolean))return nullptr;
        return Bool(MRCoreJson::Equal(Left,Right)==(Op==TEXT("eq")));
    }
    if(Op==TEXT("in"))
    {
        if(Right->Type!=EJson::Array||Right->AsArray().Num()>20000)return nullptr;
        for(const auto& Item:Right->AsArray()){if(++Work>100000)return nullptr;if(MRCoreJson::Equal(Left,Item))return Bool(true);}
        return Bool(false);
    }
    if(Left->Type!=EJson::Number||Right->Type!=EJson::Number)return nullptr;
    const double A=Left->AsNumber(),B=Right->AsNumber();
    if(Op==TEXT("lt"))return Bool(A<B);
    if(Op==TEXT("le"))return Bool(A<=B);
    if(Op==TEXT("gt"))return Bool(A>B);
    if(Op==TEXT("ge"))return Bool(A>=B);
    return nullptr;
}
}

bool MRCoreExpressions::Validate(const Object& Expression,bool ExecutionScope)
{
    if(!Expression)return false;
    const TSet<FString> Roots=ExecutionScope?TSet<FString>{TEXT("observation"),TEXT("execution"),TEXT("parameters")}:
        TSet<FString>{TEXT("protocol_version"),TEXT("episode_id"),TEXT("request_id"),TEXT("time"),TEXT("mission"),
            TEXT("agents"),TEXT("infrastructure"),TEXT("targets"),TEXT("zones"),TEXT("network"),TEXT("events"),
            TEXT("constraints"),TEXT("metrics"),TEXT("observation_quality"),TEXT("metaevolution"),
            TEXT("id"),TEXT("kind"),TEXT("position"),TEXT("status"),TEXT("capabilities"),TEXT("resources"),TEXT("communication"),
            TEXT("role"),TEXT("scenario_ids"),TEXT("available_actions"),TEXT("freshness"),TEXT("physical"),
            TEXT("geometry"),TEXT("access"),TEXT("risk"),TEXT("cost")};
    int32 Budget=0;
    const auto Type=Check(Json(Expression),{},Roots,1,Budget);
    return Type==EType::Boolean||Type==EType::Unknown;
}

Value MRCoreExpressions::Evaluate(const Object& Expression,const Object& Context)
{
    if(!Context||!Validate(Expression))return nullptr;
    int32 Work=0;return Run(Expression,Context,{},Work);
}
