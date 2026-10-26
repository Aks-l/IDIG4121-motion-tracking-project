#include "RealSenseAR.h"

#include "Interfaces/IPluginManager.h"
#include "Misc/Paths.h"
#include "Modules/ModuleManager.h"

DEFINE_LOG_CATEGORY(LogRealSense);

namespace
{
	// Linked normally on Mac and Linux, so only Windows can find it missing at runtime
	bool bLibraryLoaded = !PLATFORM_WINDOWS;
}

void FRealSenseARModule::StartupModule()
{
#if PLATFORM_WINDOWS && WITH_REALSENSE
	// realsense2.dll is delay-loaded and staged next to this plugin's binary, which is not on the
	// DLL search path, so load it explicitly before the first rs2 call
	const TSharedPtr<IPlugin> Plugin = IPluginManager::Get().FindPlugin(TEXT("RealSenseAR"));
	const FString Dll = FPaths::Combine(Plugin->GetBaseDir(), TEXT("Binaries/Win64/realsense2.dll"));
	RealSenseDllHandle = FPlatformProcess::GetDllHandle(*Dll);
	bLibraryLoaded = RealSenseDllHandle != nullptr;
	if (!bLibraryLoaded)
	{
		UE_LOG(LogRealSense, Error, TEXT("Could not load %s"), *Dll);
	}
#endif

#if !WITH_REALSENSE
	UE_LOG(LogRealSense, Warning, TEXT("RealSenseAR was built without librealsense2: the camera is disabled"));
#endif
}

void FRealSenseARModule::ShutdownModule()
{
	if (RealSenseDllHandle)
	{
		FPlatformProcess::FreeDllHandle(RealSenseDllHandle);
		RealSenseDllHandle = nullptr;
	}
}

bool FRealSenseARModule::IsLibraryLoaded()
{
	return bLibraryLoaded;
}

IMPLEMENT_MODULE(FRealSenseARModule, RealSenseAR)
