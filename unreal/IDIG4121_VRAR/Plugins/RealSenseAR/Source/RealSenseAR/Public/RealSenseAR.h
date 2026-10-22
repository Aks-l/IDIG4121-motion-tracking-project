#pragma once

#include "CoreMinimal.h"
#include "Modules/ModuleInterface.h"

REALSENSEAR_API DECLARE_LOG_CATEGORY_EXTERN(LogRealSense, Log, All);

class FRealSenseARModule : public IModuleInterface
{
public:
	virtual void StartupModule() override;
	virtual void ShutdownModule() override;

private:
	void* RealSenseDllHandle = nullptr;
};
