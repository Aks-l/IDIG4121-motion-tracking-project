#pragma once

#include "CoreMinimal.h"
#include "Subsystems/GameInstanceSubsystem.h"
#include "Tickable.h"
#include "RealSenseTypes.h"
#include "RealSenseSubsystem.generated.h"

class FRealSenseWorker;
class UTexture2D;

/**
 * The game's single door to the camera. Lives as long as the game instance (one per PIE session),
 * owns the worker thread, and once per frame on the game thread:
 *   - uploads the newest colour frame into ColorTexture (render thread, no game-thread stall)
 *   - caches the two hand anchors so every actor reads the same values this frame
 */
UCLASS()
class REALSENSEAR_API URealSenseSubsystem : public UGameInstanceSubsystem, public FTickableGameObject
{
	GENERATED_BODY()

public:
	virtual void Initialize(FSubsystemCollectionBase& Collection) override;
	virtual void Deinitialize() override;

	UFUNCTION(BlueprintCallable, Category = "RealSense")
	void StartCamera();

	UFUNCTION(BlueprintCallable, Category = "RealSense")
	void StopCamera();

	UFUNCTION(BlueprintPure, Category = "RealSense")
	bool IsStreaming() const;

	/** Why the camera stopped, empty while all is well. */
	UFUNCTION(BlueprintPure, Category = "RealSense")
	FString GetLastError() const;

	/** The live colour feed (BGRA8). Feed it to the AR background material. */
	UFUNCTION(BlueprintPure, Category = "RealSense")
	UTexture2D* GetColorTexture() const { return ColorTexture; }

	/** Invalid until the camera has started. */
	UFUNCTION(BlueprintPure, Category = "RealSense")
	FRealSenseIntrinsics GetColorIntrinsics() const;

	/** PlayerId 1 = left on screen, 2 = right. */
	UFUNCTION(BlueprintPure, Category = "RealSense")
	FRealSenseHandAnchor GetAnchor(int32 PlayerId) const;

	/** Learn the empty room after DelaySeconds, so people can step out first. */
	UFUNCTION(BlueprintCallable, Category = "RealSense")
	void RequestBackgroundCapture(float DelaySeconds = 3.f);

	/** Learn the empty room again, after the countdown from Project Settings. */
	UFUNCTION(BlueprintCallable, Category = "RealSense")
	void RecaptureBackground();

	/** Seconds until capture (> 0), 0 while capturing, < 0 when no capture is pending. */
	UFUNCTION(BlueprintPure, Category = "RealSense")
	float GetBackgroundCountdown() const;

	const FRealSenseSettings& GetSettings() const { return Settings; }

	// FTickableGameObject
	virtual void Tick(float DeltaTime) override;
	virtual ETickableTickType GetTickableTickType() const override;
	virtual bool IsTickable() const override;
	virtual TStatId GetStatId() const override;

private:
	void UploadColorFrame();

	FRealSenseSettings Settings;
	// Shared, not unique: its deleter is bound in the .cpp, so this header can keep the type incomplete
	TSharedPtr<FRealSenseWorker> Worker;

	UPROPERTY(Transient)
	TObjectPtr<UTexture2D> ColorTexture;

	TArray<uint8> ColorPixels;
	uint64 ColorSeq = 0;
	FRealSenseHandAnchor CachedAnchors[2];

	/** The automatic capture runs once per camera start. */
	bool bAutoCaptureHandled = false;
};
