#pragma once
#include "CoreMinimal.h"
#include "Engine/EngineTypes.h"
#include "InstanceDataTypes.h"

class UStaticMeshComponent;
class UInstancedStaticMeshComponent;

struct FMRStructurePiece
{
    TWeakObjectPtr<UStaticMeshComponent> Component;
    FPrimitiveInstanceId Instance;
    FTransform InitialTransform;
    FBox Bounds=FBox(ForceInit);
    ECollisionEnabled::Type Collision=ECollisionEnabled::NoCollision;
    bool Instanced=false,Removed=false,InitiallyVisible=true,InitiallyHidden=false;
    bool Remove();
    bool Restore();
};

struct FMRFireAnchor
{
    FVector Position=FVector::ZeroVector,Normal=FVector::UpVector;
    FVector Scale=FVector::OneVector;
    int32 OwnerPiece=INDEX_NONE;
    float Delay=0;
    bool Roof=false;
};

struct FMRStructureState
{
    FName Id;
    FBox Bounds=FBox(ForceInit);
    TArray<FMRStructurePiece> Pieces;
    TArray<FMRFireAnchor> FireAnchors;
};

struct FMRStructureOwner
{
    FName Structure;
    int32 Piece=INDEX_NONE;
};
