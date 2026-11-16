#pragma once
#include "CoreMinimal.h"
#include "ProceduralMeshComponent.h"

namespace MRSceneClip
{
inline FProcMeshVertex Lerp(const FProcMeshVertex& A,const FProcMeshVertex& B,double T)
{
    FProcMeshVertex R;R.Position=FMath::Lerp(A.Position,B.Position,T);
    R.Normal=FMath::Lerp(A.Normal,B.Normal,T).GetSafeNormal();
    R.Tangent=FProcMeshTangent(FMath::Lerp(A.Tangent.TangentX,B.Tangent.TangentX,T).GetSafeNormal(),A.Tangent.bFlipTangentY);
    R.UV0=FMath::Lerp(A.UV0,B.UV0,T);R.UV1=FMath::Lerp(A.UV1,B.UV1,T);
    R.UV2=FMath::Lerp(A.UV2,B.UV2,T);R.UV3=FMath::Lerp(A.UV3,B.UV3,T);
    const auto Color=FMath::Lerp(FLinearColor::FromSRGBColor(A.Color),FLinearColor::FromSRGBColor(B.Color),T);
    R.Color=Color.ToFColorSRGB();return R;
}
// Clip actual triangles, retaining their UVs, normals and material. A black
// plane over the live scene would still reveal roofs, lights and shadows.
inline void Triangle(const FProcMeshVertex& A,const FProcMeshVertex& B,const FProcMeshVertex& C,
    const FBox& Cell,FProcMeshSection& Out)
{
    TArray<FProcMeshVertex,TInlineAllocator<8>> Polygon={A,B,C};
    for(int32 Plane=0;Plane<4;++Plane)
    {
        if(Polygon.Num()<3)return;
        const int32 Axis=Plane/2;const double Limit=Plane%2?Cell.Max[Axis]:Cell.Min[Axis];
        auto Distance=[&](const FProcMeshVertex& V){return (Plane%2?-1:1)*(V.Position[Axis]-Limit);};
        TArray<FProcMeshVertex,TInlineAllocator<8>> Next;
        auto Previous=Polygon.Last();double Before=Distance(Previous);
        for(const auto& Current:Polygon)
        {
            const double After=Distance(Current);
            if((Before>=0)!=(After>=0))Next.Add(Lerp(Previous,Current,Before/(Before-After)));
            if(After>=0)Next.Add(Current);
            Previous=Current;Before=After;
        }
        Polygon=MoveTemp(Next);
    }
    if(Polygon.Num()<3)return;
    const int32 Offset=Out.ProcVertexBuffer.Num();
    for(const auto& V:Polygon){Out.ProcVertexBuffer.Add(V);Out.SectionLocalBox+=V.Position;}
    for(int32 I=1;I+1<Polygon.Num();++I)
        Out.ProcIndexBuffer.Append({uint32(Offset),uint32(Offset+I),uint32(Offset+I+1)});
    Out.bEnableCollision=false;Out.bSectionVisible=true;
}
}
