using UnrealBuildTool;

public class RealSenseAR : ModuleRules
{
	public RealSenseAR(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

		// rs.hpp reports every failure by throwing rs2::error; the worker thread catches them
		bEnableExceptions = true;

		PublicDependencyModuleNames.AddRange(new string[] {
			"Core",
			"CoreUObject",
			"Engine",
			"InputCore",
			"DeveloperSettings"
		});

		PrivateDependencyModuleNames.AddRange(new string[] {
			"RenderCore",
			"RHI",
			"Projects",
			"OpenCV",
			"OpenCVHelper",
			"LibRealSense"
		});
	}
}
