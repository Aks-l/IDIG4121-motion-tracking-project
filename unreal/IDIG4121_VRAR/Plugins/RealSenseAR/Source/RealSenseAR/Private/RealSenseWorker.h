#pragma once

#include "CoreMinimal.h"
#include "HAL/Runnable.h"
#include "RealSenseTypes.h"
#include <atomic>

class FRunnableThread;

/**
 * Owns the camera. Everything librealsense and OpenCV happens on this thread, so the game thread
 * never waits for the 30 fps camera: it only swaps out the newest results under a short lock.
 *
 *   rs2::pipeline (colour BGRA8 + depth Z16, hardware-synced framesets)
 *     colour -> back buffer -> swap with front buffer           -> TakeColorFrame()  (game thread)
 *     depth  -> decimate, threshold, spatial -> mm, mirror
 *            -> FPlayerTracker -> deproject -> depth-to-colour -> 1-euro -> GetAnchors() (game thread)
 */
class FRealSenseWorker : public FRunnable
{
public:
	explicit FRealSenseWorker(const FRealSenseSettings& InSettings);
	virtual ~FRealSenseWorker() override;

	/** Spawns the thread. The camera is opened on it, so failures show up in GetError(). */
	void Start();

	// ---- thread-safe API for the game thread

	/** Swaps the newest colour frame (BGRA8, tightly packed) into OutBGRA if it is newer than InOutSeq. */
	bool TakeColorFrame(TArray<uint8>& OutBGRA, uint64& InOutSeq);

	/** [0] = Player 1, [1] = Player 2. */
	void GetAnchors(FRealSenseHandAnchor (&OutAnchors)[2]) const;

	/** Invalid until the camera has started. */
	FRealSenseIntrinsics GetColorIntrinsics() const;

	/** Learn the empty room after DelaySeconds (so people can step out). */
	void RequestBackground(double DelaySeconds);

	/** Seconds until capture (> 0), 0 while capturing, < 0 when no capture is pending. */
	double GetBackgroundCountdown() const;

	bool IsStreaming() const { return bStreaming; }
	FString GetError() const;

	// ---- FRunnable
	virtual uint32 Run() override;
	virtual void Stop() override { bStopRequested = true; }

private:
	struct FImpl;

	void SetError(const FString& Message);

	const FRealSenseSettings Settings;
	TUniquePtr<FImpl> Impl;   // librealsense / OpenCV state, kept out of this header
	FRunnableThread* Thread = nullptr;

	std::atomic<bool> bStopRequested{ false };
	std::atomic<bool> bStreaming{ false };

	mutable FCriticalSection Lock;
	// Everything below is guarded by Lock
	TArray<uint8> ColorFront;
	uint64 ColorSeq = 0;
	FRealSenseHandAnchor Anchors[2];
	FRealSenseIntrinsics ColorIntrinsics;
	double BackgroundCaptureAt = -1.0;
	FString Error;
};
