#include "MRCityAssets.h"
#include "Engine/StaticMesh.h"
#include "Materials/MaterialInterface.h"
#include "Dom/JsonObject.h"
#include "Serialization/JsonSerializer.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"

namespace
{
TSharedPtr<FJsonObject> CityAssets;
TSharedPtr<FJsonObject> CityMaterials;
bool bReadCityAssets=false;

UStaticMesh* CatalogMesh(const FString& Filename,const FString& Format,const FString& Folder,const FString& AssetId)
{
    static TMap<FString,TMap<FString,FString>> Catalogs;
    auto& Paths=Catalogs.FindOrAdd(Filename);
    if(Paths.IsEmpty())
    {
        FString Text;TSharedPtr<FJsonObject> Manifest;
        if(!FFileHelper::LoadFileToString(Text,*(FPaths::ProjectContentDir()/Filename))||
           !FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text),Manifest)||!Manifest||
           Manifest->GetStringField(TEXT("format"))!=Format)return nullptr;
        for(const auto& Value:Manifest->GetArrayField(TEXT("models")))
        {
            const auto Model=Value->AsObject();
            const FString Path=Model->GetStringField(TEXT("mesh"));
            if(Path.StartsWith(Folder))Paths.Add(Model->GetStringField(TEXT("id")),Path);
        }
    }
    const auto* Path=Paths.Find(AssetId);
    return Path?LoadObject<UStaticMesh>(nullptr,**Path):nullptr;
}

TArray<FMRCityMeshPart> Parts(const TSharedPtr<FJsonObject>& Record)
{
    TArray<FMRCityMeshPart> Result;
    for(const auto& Value:Record->GetArrayField(TEXT("parts")))
    {
        auto J=Value->AsObject();auto* Mesh=LoadObject<UStaticMesh>(nullptr,*J->GetStringField(TEXT("mesh")));
        if(Mesh)Result.Add({Mesh,J->GetStringField(TEXT("kind"))==TEXT("glass")});
        else UE_LOG(LogTemp,Error,TEXT("MR_CITY missing derived mesh %s"),*J->GetStringField(TEXT("mesh")));
    }
    return Result;
}
}

bool MRCityAssetsReady()
{
    if(!bReadCityAssets)
    {
        bReadCityAssets=true;FString Text;
        if(FFileHelper::LoadFileToString(Text,*(FPaths::ProjectContentDir()/TEXT("Scenario/city-assets.json"))))
            FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text),CityAssets);
        if(FFileHelper::LoadFileToString(Text,*(FPaths::ProjectContentDir()/TEXT("Scenario/city-materials.json"))))
            FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text),CityMaterials);
    }
    return CityAssets.IsValid()&&CityAssets->GetBoolField(TEXT("native_geometry_verified"))&&CityMaterials.IsValid();
}

UMaterialInterface* MRCityMaterial(UMaterialInterface* Source)
{
    if(Source&&MRCityAssetsReady())
    {
        FString Path;
        if(CityMaterials->GetObjectField(TEXT("replacements"))->TryGetStringField(Source->GetPathName(),Path))
            if(auto* Material=LoadObject<UMaterialInterface>(nullptr,*Path))return Material;
    }
    return Source;
}

UStaticMesh* MRCityFoliage(int32 Model)
{
    static TSharedPtr<FJsonObject> Foliage;static bool Read=false;
    if(!Read)
    {
        Read=true;FString Text;
        if(FFileHelper::LoadFileToString(Text,*(FPaths::ProjectContentDir()/TEXT("Scenario/city-foliage.json"))))
            FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text),Foliage);
    }
    if(Foliage)for(const auto& Entry:Foliage->GetArrayField(TEXT("models")))
    {
        auto J=Entry->AsObject();if(J->GetIntegerField(TEXT("variant"))==Model)return LoadObject<UStaticMesh>(nullptr,*J->GetStringField(TEXT("mesh")));
    }
    return nullptr;
}

UStaticMesh* MRCityVegetation(const FString& AssetId,int32 Revision)
{
    const FString Suffix=Revision==1?FString():FString::Printf(TEXT("-r%d"),Revision);
    const FString Filename=TEXT("Scenario/city-vegetation-v2")+Suffix+TEXT(".json");
    const FString Format=Revision==1?TEXT("metarescue.city-vegetation.v2"):
        FString::Printf(TEXT("metarescue.city-vegetation.v2.r%d"),Revision);
    const FString Folder=Revision==1?TEXT("/Game/RescueAssets/CityV2/Vegetation/"):
        FString::Printf(TEXT("/Game/RescueAssets/CityV2/VegetationR%d/"),Revision);
    return CatalogMesh(Filename,Format,Folder,AssetId);
}

UStaticMesh* MRCityProp(const FString& AssetId)
{
    return CatalogMesh(TEXT("Scenario/city-props-v1.json"),TEXT("metarescue.city-props.v1"),
                       TEXT("/Game/RescueAssets/CityV2/Props/"),AssetId);
}

TArray<FMRCityMeshPart> MRCityMeshParts(UStaticMesh* Source)
{
    if(Source&&MRCityAssetsReady())
    {
        auto Map=CityAssets->GetObjectField(TEXT("replacements"));const TSharedPtr<FJsonObject>* Record=nullptr;
        if(Map->TryGetObjectField(Source->GetPathName(),Record))return Parts(*Record);
    }
    return Source?TArray<FMRCityMeshPart>{{Source,false}}:TArray<FMRCityMeshPart>{};
}

UStaticMesh* MRCityBakedBox(FVector SizeCm)
{
    if(!MRCityAssetsReady())return nullptr;
    const FString Key=FString::Printf(TEXT("%.3f,%.3f,%.3f"),SizeCm.X,SizeCm.Y,SizeCm.Z);
    const TSharedPtr<FJsonObject>* Record=nullptr;
    if(CityAssets->GetObjectField(TEXT("baked_boxes_cm"))->TryGetObjectField(Key,Record))
    {
        const auto Entries=Parts(*Record);if(!Entries.IsEmpty())return Entries[0].Mesh;
    }
    return nullptr;
}
