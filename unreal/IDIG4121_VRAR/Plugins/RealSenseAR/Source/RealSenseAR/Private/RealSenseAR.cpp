#include "RealSenseAR.h"

#include "Interfaces/IPluginManager.h"
#include "Misc/Paths.h"
#include "Modules/ModuleManager.h"

DEFINE_LOG_CATEGORY(LogRealSense);

void FRealSenseARModule::StartupModule()
{
#if PLATFORM_WINDOWS
	// realsense2.dll is delay-loaded and staged next to this plugin's binary, which is not on the
	// DLL search path, so load it explicitly before the first rs2 call
	const TSharedPtr<IPlugin> Plugin = IPluginManager::Get().FindPlugin(TEXT("RealSenseAR"));
	const FString Dll = FPaths::Combine(Plugin->GetBaseDir(), TEXT("Binaries/Win64/realsense2.dll"));
	RealSenseDllHandle = FPlatformProcess::GetDllHandle(*Dll);
	if (!RealSenseDllHandle)
	{
		UE_LOG(LogRealSense, Error, TEXT("Could not load %s"), *Dll);
	}
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

IMPLEMENT_MODULE(FRealSenseARModule, RealSenseAR)
