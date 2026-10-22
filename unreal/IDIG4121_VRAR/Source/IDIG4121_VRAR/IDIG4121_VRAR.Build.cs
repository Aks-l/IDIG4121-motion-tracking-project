// Copyright Epic Games, Inc. All Rights Reserved.

using UnrealBuildTool;

public class IDIG4121_VRAR : ModuleRules
{
	public IDIG4121_VRAR(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

		PublicDependencyModuleNames.AddRange(new string[] {
			"Core",
			"CoreUObject",
			"Engine",
			"InputCore",
			"EnhancedInput",
			"AIModule",
			"StateTreeModule",
			"GameplayStateTreeModule",
			"UMG",
			"Slate",
			"RealSenseAR"
		});

		PrivateDependencyModuleNames.AddRange(new string[] { });

		PublicIncludePaths.AddRange(new string[] {
			"IDIG4121_VRAR",
			"IDIG4121_VRAR/CoopAR",
			"IDIG4121_VRAR/Variant_Horror",
			"IDIG4121_VRAR/Variant_Horror/UI",
			"IDIG4121_VRAR/Variant_Shooter",
			"IDIG4121_VRAR/Variant_Shooter/AI",
			"IDIG4121_VRAR/Variant_Shooter/UI",
			"IDIG4121_VRAR/Variant_Shooter/Weapons"
		});

		// Uncomment if you are using Slate UI
		// PrivateDependencyModuleNames.AddRange(new string[] { "Slate", "SlateCore" });

		// Uncomment if you are using online features
		// PrivateDependencyModuleNames.Add("OnlineSubsystem");

		// To include OnlineSubsystemSteam, add it to the plugins section in your uproject file with the Enabled attribute set to true
	}
}
