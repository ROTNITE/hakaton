using UnrealBuildTool;
public class MetaRescue : ModuleRules
{
    public MetaRescue(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
        PublicDependencyModuleNames.AddRange(new string[] {
            "Core", "CoreUObject", "Engine", "InputCore", "Json", "JsonUtilities",
            "PhysicsCore", "ProceduralMeshComponent", "Niagara", "HTTPServer"
        });
        PrivateDependencyModuleNames.AddRange(new string[] { "Slate", "SlateCore", "HTTP" });
        if(Target.bBuildEditor)PrivateDependencyModuleNames.AddRange(new string[] {
            "NiagaraEditor", "MeshDescription", "StaticMeshDescription", "AssetRegistry"
        });
    }
}
