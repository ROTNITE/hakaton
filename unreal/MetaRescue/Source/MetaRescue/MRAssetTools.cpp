#include "MRAssetTools.h"
#include "MRAssetAssembly.h"
#include "NiagaraSystem.h"
#include "NiagaraEmitter.h"
#include "NiagaraSpriteRendererProperties.h"
#include "NiagaraScript.h"
#include "Materials/MaterialInterface.h"
#include "UObject/Package.h"
#include "Misc/PackageName.h"
#include "Engine/StaticMesh.h"
#include "StaticMeshResources.h"
#include "Dom/JsonObject.h"
#include "Serialization/JsonSerializer.h"
#include "Misc/SecureHash.h"
#if WITH_EDITOR
#include "MeshDescription.h"
#include "StaticMeshAttributes.h"
#include "AssetCompilingManager.h"
#include "AssetRegistry/AssetRegistryModule.h"
#include "PhysicsEngine/BodySetup.h"
#include "NiagaraSystemFactoryNew.h"
#include "NiagaraEditorUtilities.h"
#endif

FString UMRAssetTools::DescribeMeshGeometry(UStaticMesh* Mesh)
{
    auto Result=MakeShared<FJsonObject>();
    Result->SetBoolField(TEXT("available"),false);
#if WITH_EDITOR
    if(Mesh&&Mesh->GetNumSourceModels()>0)
    {
        const auto RenderBounds=Mesh->GetBounds();
        const FMeshDescription* Description=Mesh->GetMeshDescription(0);
        if(Description)
        {
            const FVector Scale=Mesh->GetSourceModel(0).BuildSettings.BuildScale3D;
            FBox Bounds(ForceInit);FSHA1 Hash;
            for(const FVertexID Vertex:Description->Vertices().GetElementIDs())
            {
                const int32 Id=Vertex.GetValue();const FVector3f Raw=Description->GetVertexPosition(Vertex);
                Hash.Update(reinterpret_cast<const uint8*>(&Id),sizeof(Id));
                Hash.Update(reinterpret_cast<const uint8*>(&Raw),sizeof(Raw));
                Bounds+=FVector(Raw)*Scale;
            }
            for(const FTriangleID Triangle:Description->Triangles().GetElementIDs())
            {
                const int32 Id=Triangle.GetValue();Hash.Update(reinterpret_cast<const uint8*>(&Id),sizeof(Id));
                for(const FVertexID Vertex:Description->GetTriangleVertices(Triangle))
                {const int32 Value=Vertex.GetValue();Hash.Update(reinterpret_cast<const uint8*>(&Value),sizeof(Value));}
            }
            Hash.Final();uint8 Digest[FSHA1::DigestSize];Hash.GetHash(Digest);
            Result->SetBoolField(TEXT("available"),true);
            Result->SetStringField(TEXT("raw_geometry_sha1"),BytesToHex(Digest,FSHA1::DigestSize));
            Result->SetNumberField(TEXT("vertices"),Description->Vertices().Num());
            Result->SetNumberField(TEXT("triangles"),Description->Triangles().Num());
            Result->SetBoolField(TEXT("nanite_enabled"),Mesh->GetNaniteSettings().bEnabled);
            Result->SetNumberField(TEXT("fallback_triangle_fraction"),Mesh->GetNaniteSettings().FallbackPercentTriangles);
            Result->SetStringField(TEXT("fallback_target"),Mesh->GetNaniteSettings().FallbackTarget==ENaniteFallbackTarget::PercentTriangles?TEXT("percent_triangles"):TEXT("other"));
            TArray<TSharedPtr<FJsonValue>> Groups,Sections;
            FStaticMeshConstAttributes Attributes(*Description);
            const auto Slots=Attributes.GetPolygonGroupMaterialSlotNames();
            for(const FPolygonGroupID Group:Description->PolygonGroups().GetElementIDs())
            {
                auto Entry=MakeShared<FJsonObject>();
                Entry->SetStringField(TEXT("slot"),Slots[Group].ToString());
                Entry->SetNumberField(TEXT("triangles"),Description->GetPolygonGroupTriangles(Group).Num());
                Groups.Add(MakeShared<FJsonValueObject>(Entry));
            }
            if(const auto* Render=Mesh->GetRenderData();Render&&Render->LODResources.Num())
            {
                const auto& Built=Render->LODResources[0].Sections;
                for(int32 Index=0;Index<Built.Num();Index++)
                {
                    const auto& Section=Built[Index];auto Entry=MakeShared<FJsonObject>();
                    Entry->SetNumberField(TEXT("section"),Index);
                    Entry->SetNumberField(TEXT("material_index"),Section.MaterialIndex);
                    Entry->SetNumberField(TEXT("configured_material_index"),Mesh->GetSectionInfoMap().Get(0,Index).MaterialIndex);
                    Entry->SetNumberField(TEXT("triangles"),Section.NumTriangles);
                    const auto* Material=Mesh->GetMaterial(Section.MaterialIndex);
                    Entry->SetStringField(TEXT("material"),GetPathNameSafe(Material));
                    Entry->SetNumberField(TEXT("blend_mode"),Material?int32(Material->GetBlendMode()):-1);
                    if(Mesh->GetStaticMaterials().IsValidIndex(Section.MaterialIndex))
                        Entry->SetStringField(TEXT("slot"),Mesh->GetStaticMaterials()[Section.MaterialIndex].ImportedMaterialSlotName.ToString());
                    Sections.Add(MakeShared<FJsonValueObject>(Entry));
                }
            }
            Result->SetArrayField(TEXT("source_groups"),Groups);
            Result->SetArrayField(TEXT("render_sections"),Sections);
            auto Vector=[&](const TCHAR* Name,FVector Value)
            {
                TArray<TSharedPtr<FJsonValue>> Values;
                for(double V:{Value.X,Value.Y,Value.Z})Values.Add(MakeShared<FJsonValueNumber>(V));
                Result->SetArrayField(Name,Values);
            };
            Vector(TEXT("source_min_cm"),Bounds.Min);Vector(TEXT("source_max_cm"),Bounds.Max);
            Vector(TEXT("build_scale"),Scale);
            Vector(TEXT("render_extent_cm"),RenderBounds.BoxExtent);
            Vector(TEXT("positive_bounds_extension_cm"),Mesh->GetPositiveBoundsExtension());
            Vector(TEXT("negative_bounds_extension_cm"),Mesh->GetNegativeBoundsExtension());
        }
    }
#endif
    FString Text;FJsonSerializer::Serialize(Result,TJsonWriterFactory<TCHAR,TCondensedJsonPrintPolicy<TCHAR>>::Create(&Text));
    return Text;
}

void UMRAssetTools::FinishAssetCompilation()
{
#if WITH_EDITOR
    FAssetCompilingManager::Get().FinishAllCompilation();
#endif
}

#if WITH_EDITOR
namespace
{
TArray<FString> MRTriangleGeometry(UStaticMesh* Mesh,FVector ExtraScale)
{
    TArray<FString> Result;
    const FMeshDescription* D=Mesh->GetMeshDescription(0);
    if(!D)return Result;
    const FVector Scale=Mesh->GetSourceModel(0).BuildSettings.BuildScale3D*ExtraScale;
    FStaticMeshConstAttributes Attributes(*D);
    const auto Normals=Attributes.GetVertexInstanceNormals();
    const auto UVs=Attributes.GetVertexInstanceUVs();
    const auto Slots=Attributes.GetPolygonGroupMaterialSlotNames();
    for(FTriangleID Triangle:D->Triangles().GetElementIDs())
    {
        FSHA1 Hash;
        for(FVertexInstanceID Instance:D->GetTriangleVertexInstances(Triangle))
        {
            const FVector3f P(FVector(D->GetVertexPosition(D->GetVertexInstanceVertex(Instance)))*Scale);
            const FVector3f N=Normals[Instance];
            Hash.Update(reinterpret_cast<const uint8*>(&P),sizeof(P));
            Hash.Update(reinterpret_cast<const uint8*>(&N),sizeof(N));
            for(int32 Channel=0;Channel<UVs.GetNumChannels();Channel++)
            {
                const FVector2f UV=UVs.Get(Instance,Channel);
                Hash.Update(reinterpret_cast<const uint8*>(&UV),sizeof(UV));
            }
        }
        const FString Slot=Slots[D->GetTrianglePolygonGroup(Triangle)].ToString();
        FTCHARToUTF8 Utf8(*Slot);Hash.Update(reinterpret_cast<const uint8*>(Utf8.Get()),Utf8.Length());
        Hash.Final();uint8 Digest[FSHA1::DigestSize];Hash.GetHash(Digest);Result.Add(BytesToHex(Digest,FSHA1::DigestSize));
    }
    Result.Sort();return Result;
}
}
#endif

FString UMRAssetTools::PrepareCityMesh(UStaticMesh* Source,const FString& PackageBase,FVector BakedScale)
{
    auto Result=MakeShared<FJsonObject>();Result->SetBoolField(TEXT("verified"),false);
#if WITH_EDITOR
    const bool bCityPackage=PackageBase.StartsWith(TEXT("/Game/RescueAssets/CityV1/"))||
        PackageBase.StartsWith(TEXT("/Game/RescueAssets/CityV2/"));
    if(!Source||!Source->GetMeshDescription(0)||!bCityPackage||
        !FPackageName::IsValidLongPackageName(PackageBase)||BakedScale.ContainsNaN()||BakedScale.GetMin()<=0)return TEXT("{}");
    const auto Expected=MRTriangleGeometry(Source,BakedScale);
    TArray<FString> Actual;TArray<TSharedPtr<FJsonValue>> Parts;
    TArray<bool> Opaque;
    const auto& SourceMaterials=Source->GetStaticMaterials();
    UMaterialInterface* FirstOpaque=nullptr;
    for(const auto& Slot:SourceMaterials)
    {
        UMaterialInterface* Material=MRSceneMaterial(Slot.MaterialInterface);
        const bool Supported=Material&&(Material->GetBlendMode()==BLEND_Opaque||Material->GetBlendMode()==BLEND_Masked);
        Opaque.Add(Supported);if(Supported&&!FirstOpaque)FirstOpaque=Material;
    }
    for(bool WantOpaque:{true,false})
    {
        const FString Name=PackageBase+(WantOpaque?TEXT("_opaque"):TEXT("_glass"));
        UStaticMesh* Copy=LoadObject<UStaticMesh>(nullptr,*Name);
        if(!Copy)
        {
            UPackage* Package=CreatePackage(*Name);
            Copy=DuplicateObject<UStaticMesh>(Source,Package,*FPackageName::GetLongPackageAssetName(Name));
            Copy->SetFlags(RF_Public|RF_Standalone);Copy->SetNumSourceModels(1);
            FMeshDescription* D=Copy->GetMeshDescription(0);FStaticMeshAttributes Attributes(*D);
            const auto Slots=Attributes.GetPolygonGroupMaterialSlotNames();TArray<FPolygonID> Remove;
            for(FPolygonID Polygon:D->Polygons().GetElementIDs())
            {
                const FName SlotName=Slots[D->GetPolygonPolygonGroup(Polygon)];
                const int32 Slot=SourceMaterials.IndexOfByPredicate([&](const FStaticMaterial& M){return M.ImportedMaterialSlotName==SlotName;});
                if(!Opaque.IsValidIndex(Slot))return TEXT("{\"error\":\"unmapped material slot\"}");
                if(Opaque[Slot]!=WantOpaque)Remove.Add(Polygon);
            }
            if(Remove.Num()==D->Polygons().Num())
            {Copy->ClearFlags(RF_Public|RF_Standalone);Copy->MarkAsGarbage();continue;}
            if(!Remove.IsEmpty())D->DeletePolygons(Remove);
            TArray<FPolygonGroupID> EmptyGroups;
            for(const FPolygonGroupID Group:D->PolygonGroups().GetElementIDs())
                if(D->GetPolygonGroupTriangles(Group).IsEmpty())EmptyGroups.Add(Group);
            for(const FPolygonGroupID Group:EmptyGroups)D->DeletePolygonGroup(Group);
            FElementIDRemappings Remap;D->Compact(Remap);
            // Built sections are renumbered after filtering. A duplicated old
            // section 0 can bind a surviving pane to the frame's opaque atlas.
            Copy->GetSectionInfoMap().Clear();Copy->GetOriginalSectionInfoMap().Clear();
            const auto PartSlots=FStaticMeshAttributes(*D).GetPolygonGroupMaterialSlotNames();
            int32 SectionIndex=0;
            for(const FPolygonGroupID Group:D->PolygonGroups().GetElementIDs())
            {
                const FName SlotName=PartSlots[Group];
                const int32 MaterialIndex=SourceMaterials.IndexOfByPredicate([&](const FStaticMaterial& M){return M.ImportedMaterialSlotName==SlotName;});
                if(!SourceMaterials.IsValidIndex(MaterialIndex))return TEXT("{\"error\":\"unmapped filtered section\"}");
                FMeshSectionInfo Info;Info.MaterialIndex=MaterialIndex;
                Info.bEnableCollision=WantOpaque;Info.bCastShadow=WantOpaque;
                Copy->GetSectionInfoMap().Set(0,SectionIndex,Info);
                Copy->GetOriginalSectionInfoMap().Set(0,SectionIndex,Info);SectionIndex++;
            }
            for(int32 I=0;I<Copy->GetStaticMaterials().Num();I++)
            {
                auto& Slot=Copy->GetStaticMaterials()[I];Slot.MaterialInterface=MRSceneMaterial(Slot.MaterialInterface);
                // Unused translucent slots must not invalidate the opaque mesh.
                if(WantOpaque&&!Opaque[I])Slot.MaterialInterface=FirstOpaque;
            }
            auto& Build=Copy->GetSourceModel(0).BuildSettings;
            Build.BuildScale3D*=BakedScale;Build.DistanceFieldResolutionScale=3;
            Build.MaxLumenMeshCards=32;
            Copy->GetNaniteSettings().bEnabled=WantOpaque;
            Copy->GetNaniteSettings().KeepPercentTriangles=1;
            // Static physical collision uses the fallback triangles. Keep the
            // full mesh, including window/door apertures and narrow supports.
            Copy->GetNaniteSettings().FallbackTarget=ENaniteFallbackTarget::PercentTriangles;
            Copy->GetNaniteSettings().FallbackPercentTriangles=1;
            Copy->GetNaniteSettings().FallbackRelativeError=0;
            Copy->CommitMeshDescription(0);
            if(Copy->GetBodySetup())Copy->GetBodySetup()->CollisionTraceFlag=CTF_UseComplexAsSimple;
            FAssetRegistryModule::AssetCreated(Copy);Copy->MarkPackageDirty();Copy->PostEditChange();
        }
        FAssetCompilingManager::Get().FinishAllCompilation();
        const auto* Render=Copy->GetRenderData();
        if(!Render||Render->LODResources.IsEmpty())return TEXT("{\"error\":\"missing built sections\"}");
        for(const auto& Section:Render->LODResources[0].Sections)
        {
            if(!Section.NumTriangles)continue;
            const auto* Material=Copy->GetMaterial(Section.MaterialIndex);
            const bool IsOpaque=Material&&(Material->GetBlendMode()==BLEND_Opaque||Material->GetBlendMode()==BLEND_Masked);
            if(!Material||IsOpaque!=WantOpaque)return TEXT("{\"error\":\"built section has wrong opacity binding\"}");
        }
        const auto Geometry=MRTriangleGeometry(Copy,FVector::OneVector);Actual.Append(Geometry);
        auto Part=MakeShared<FJsonObject>();Part->SetStringField(TEXT("mesh"),Copy->GetPathName());
        Part->SetStringField(TEXT("kind"),WantOpaque?TEXT("opaque"):TEXT("glass"));
        Part->SetNumberField(TEXT("triangles"),Geometry.Num());
        Part->SetBoolField(TEXT("nanite"),Copy->GetNaniteSettings().bEnabled);
        Parts.Add(MakeShared<FJsonValueObject>(Part));
    }
    Actual.Sort();Result->SetBoolField(TEXT("verified"),Expected==Actual);
    Result->SetNumberField(TEXT("source_triangles"),Expected.Num());Result->SetArrayField(TEXT("parts"),Parts);
    Result->SetBoolField(TEXT("render_sections_verified"),Expected==Actual);
    Result->SetStringField(TEXT("check"),TEXT("all source triangles, positions, normals, UV channels and material slots preserved exactly across parts"));
#endif
    FString Text;FJsonSerializer::Serialize(Result,TJsonWriterFactory<TCHAR,TCondensedJsonPrintPolicy<TCHAR>>::Create(&Text));return Text;
}

UNiagaraSystem* UMRAssetTools::CreateEffect(const FString& EmitterPath,const FString& PackagePath,UMaterialInterface* Material)
{
#if WITH_EDITOR
    // A package may exist on disk without any loaded objects. Load it before
    // testing FindObject; creating a second object at that path corrupts saves.
    const FString ObjectPath=PackagePath+TEXT(".")+FPackageName::GetLongPackageAssetName(PackagePath);
    auto* System=LoadObject<UNiagaraSystem>(nullptr,*ObjectPath);
    auto* Source=LoadObject<UNiagaraEmitter>(nullptr,*EmitterPath);
    if(!Source||!Material)return nullptr;
    auto* Package=CreatePackage(*PackagePath);
    if(!System)
    {
        System=NewObject<UNiagaraSystem>(Package,*FPackageName::GetLongPackageAssetName(PackagePath),RF_Public|RF_Standalone);
        UNiagaraSystemFactoryNew::InitializeSystem(System,true);
    }
    // A raw emitter handle does not wire its spawn/update nodes into the system
    // graph. Rebuild also repairs older generated assets with empty execution.
    TSet<FGuid> OldHandles;
    for(const auto& Handle:System->GetEmitterHandles())OldHandles.Add(Handle.GetId());
    if(!OldHandles.IsEmpty())System->RemoveEmitterHandlesById(OldHandles);
    FNiagaraEditorUtilities::AddEmitterToSystem(*System,*Source,Source->GetExposedVersion().VersionGuid);
    for(auto& Handle:System->GetEmitterHandles())
        for(auto* Renderer:Handle.GetEmitterData()->GetRenderers())
            if(auto* Sprite=Cast<UNiagaraSpriteRendererProperties>(Renderer))
            {
                Sprite->Material=Material;
                if(PackagePath.Contains(TEXT("EffectsV3")))
                {
                    const FNiagaraVariable Binding(FNiagaraTypeDefinition::GetUMaterialDef(),TEXT("User.EffectMaterial"));
                    System->GetExposedParameters().AddParameter(Binding);
                    System->GetExposedParameters().SetUObject(Material,Binding);
                    Sprite->MaterialUserParamBinding.Parameter=Binding;
                }
            }
    System->RequestCompile(true);System->WaitForCompilationComplete(true,false);
    System->MarkPackageDirty();return System;
#else
    return nullptr;
#endif
}

FString UMRAssetTools::DescribeEffect(UNiagaraSystem* System)
{
    FString Result;if(!System)return TEXT("null");
    for(const auto& Handle:System->GetEmitterHandles())
    {
        TArray<UNiagaraScript*> Scripts;Handle.GetEmitterData()->GetScripts(Scripts,false);
        for(auto* Script:Scripts)if(Script)
            Result+=Script->GetName()+TEXT("\n")+Script->RapidIterationParameters.ToString()+TEXT("\n");
    }
    return Result;
}

void UMRAssetTools::ConfigureEffect(UNiagaraSystem* System,float Rate,float LifetimeMin,float LifetimeMax,
    float SizeMin,float SizeMax,float SpeedMin,float SpeedMax,FVector Gravity,float Spread)
{
#if WITH_EDITOR
    if(!System)return;
    const bool DetailedFire=System->GetPathName().Contains(TEXT("/Revision5/"))&&System->GetName().Contains(TEXT("BuildingFire"));
    const float Lifetime=FMath::Max(LifetimeMin,LifetimeMax);
    const float Width=Spread+SizeMax+SpeedMax*.58f*Lifetime+15.f*Lifetime;
    const float Height=Spread+SizeMax+SpeedMax*Lifetime+FMath::Max(0.f,float(Gravity.Z))*.5f*Lifetime*Lifetime;
    const float Drop=SizeMax+FMath::Max(0.f,float(-Gravity.Z))*.5f*Lifetime*Lifetime;
    System->bFixedBounds=true;System->SetFixedBounds(FBox(FVector(-Width,-Width,-Drop),FVector(Width,Width,Height)));
    for(auto& Handle:System->GetEmitterHandles())
    {
        auto* Data=Handle.GetEmitterData();Data->bDeterminism=true;Data->RandomSeed=831;
        Data->bLocalSpace=!System->GetName().Contains(TEXT("WheelSplash"));
        if(DetailedFire)for(auto* Renderer:Data->GetRenderers())
            if(auto* Sprite=Cast<UNiagaraSpriteRendererProperties>(Renderer))
            {
                Sprite->Alignment=ENiagaraSpriteAlignment::Unaligned;
                Sprite->FacingMode=ENiagaraSpriteFacingMode::FaceCameraPosition;
                Sprite->PivotInUVSpace=FVector2D(.5,.92);
            }
        TArray<UNiagaraScript*> Scripts;Data->GetScripts(Scripts,false);
        for(auto* Script:Scripts)if(Script)
        {
            TArray<FNiagaraVariable> Vars;Script->RapidIterationParameters.GetParameters(Vars);
            for(const auto& V:Vars)
            {
                const FString Name=V.GetName().ToString();float Value=0;bool Set=false;
                for(const auto& Pair:TArray<TPair<FString,float>>{
                    {TEXT("SpawnRate.SpawnRate"),Rate},{TEXT("InitializeParticle.Lifetime Min"),LifetimeMin},
                    {TEXT("InitializeParticle.Lifetime Max"),LifetimeMax},{TEXT("InitializeParticle.Uniform Sprite Size Min"),SizeMin},
                    {TEXT("InitializeParticle.Uniform Sprite Size Max"),SizeMax},{TEXT("RandomRangeFloat.Minimum"),SpeedMin},
                    {TEXT("RandomRangeFloat.Maximum"),SpeedMax},{TEXT("ShapeLocation.Sphere Radius"),Spread},
                    {TEXT("AddVelocity.Cone Angle"),DetailedFire?8.f:35.f}})
                    if(Name.EndsWith(Pair.Key)){Value=Pair.Value;Set=true;break;}
                if(Set&&V.GetSizeInBytes()==sizeof(float))Script->RapidIterationParameters.SetParameterValue(Value,V);
                if(DetailedFire&&V.GetSizeInBytes()==sizeof(float)&&
                    (Name.EndsWith(TEXT("InitializeParticle.Sprite Rotation Angle Min"))||
                     Name.EndsWith(TEXT("InitializeParticle.Sprite Rotation Angle Max"))))
                    Script->RapidIterationParameters.SetParameterValue(0.f,V);
                if(Name.EndsWith(TEXT("GravityForce.Gravity")))Script->RapidIterationParameters.SetParameterValue(FVector3f(Gravity),V);
                if(Name.EndsWith(TEXT("AddVelocity.Velocity")))Script->RapidIterationParameters.SetParameterValue(FVector3f(15,5,30),V);
            }
        }
    }
    System->RequestCompile(true);System->WaitForCompilationComplete(true,false);System->MarkPackageDirty();
#endif
}
