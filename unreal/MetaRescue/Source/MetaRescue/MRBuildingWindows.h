#pragma once

#include "CoreMinimal.h"

inline const TCHAR* MRApartmentWindowStyle(int32 Damage,int32 Variant,int32 Level,int32 Side,int32 Bay)
{
    const int32 Choice=(Variant*13+Level*7+Bay*3+Side)%10;
    if(Damage==0)return Choice<8?TEXT("clean"):TEXT("dirty");
    return Choice<2?TEXT("dirty"):Choice<5?TEXT("cracked"):Choice<8?TEXT("broken"):TEXT("empty");
}
