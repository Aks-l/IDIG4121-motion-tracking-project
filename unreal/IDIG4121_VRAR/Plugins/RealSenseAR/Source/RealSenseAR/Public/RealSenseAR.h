#pragma once

#include "CoreMinimal.h"
#include "Modules/ModuleInterface.h"

REALSENSEAR_API DECLARE_LOG_CATEGORY_EXTERN(LogRealSense, Log, All);

class FRealSenseARModule : public IModuleInterface
{
public:
	virtual void StartupModule() override;
	virtual void ShutdownModule() override;

	/** False when librealsense2 could not be loaded (Windows delay-loads realsense2.dll). */
	static bool IsLibraryLoaded();

private:
	void* RealSenseDllHandle = nullptr;
};
