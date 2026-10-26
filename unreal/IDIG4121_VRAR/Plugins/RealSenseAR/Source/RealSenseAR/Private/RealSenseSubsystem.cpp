#include "RealSenseSubsystem.h"

#include "Engine/Texture2D.h"
#include "RealSenseAR.h"
#include "RealSenseWorker.h"
#include "RenderingThread.h"
#include "RHICommandList.h"
#include "TextureResource.h"

namespace
{
	/** The pixels move into the render command, which frees them once uploaded: the game thread never waits on the GPU. */
	void EnqueueUpload(UTexture2D* Texture, TArray<uint8>&& Pixels)
	{
		FTextureResource* Resource = Texture->GetResource();
		const uint32 Width = Texture->GetSizeX();
		const uint32 Height = Texture->GetSizeY();
		ENQUEUE_RENDER_COMMAND(UpdateRealSenseTexture)(
			[Resource, Width, Height, Pixels = MoveTemp(Pixels)](FRHICommandListImmediate& RHICmdList)
			{
				if (Resource && Resource->TextureRHI)
				{
					const FUpdateTextureRegion2D Region(0, 0, 0, 0, Width, Height);
					RHICmdList.UpdateTexture2D(Resource->TextureRHI.GetReference(), 0, Region, Width * 4, Pixels.GetData());
				}
			});
	}
}

void URealSenseSubsystem::Initialize(FSubsystemCollectionBase& Collection)
{
	Super::Initialize(Collection);

	const URealSenseProjectSettings* Project = GetDefault<URealSenseProjectSettings>();
	Settings = Project->Settings;

	// Created up front at the requested size, so materials can bind it before the first frame.
	// SRGB off: the background is composited after the tonemapper, where values are already
	// display-encoded, so the camera's bytes must reach the screen untouched.
	// Starts black: without initial data the GPU memory is undefined and shows as noise until a frame arrives.
	TArray64<uint8> Black;
	Black.SetNumZeroed(int64(Settings.ColorWidth) * Settings.ColorHeight * 4);
	ColorTexture = UTexture2D::CreateTransient(Settings.ColorWidth, Settings.ColorHeight, PF_B8G8R8A8, TEXT("RealSenseColor"), Black);
	ColorTexture->SRGB = false;
	ColorTexture->Filter = TF_Bilinear;
	ColorTexture->AddressX = TA_Clamp;
	ColorTexture->AddressY = TA_Clamp;
	ColorTexture->NeverStream = true;
	ColorTexture->UpdateResource();

	if (Project->bAutoStart)
	{
		StartCamera();
	}
}

void URealSenseSubsystem::Deinitialize()
{
	// Joins the thread and releases the camera, so the next PIE session can open it again
	StopCamera();
	Super::Deinitialize();
}

void URealSenseSubsystem::StartCamera()
{
	if (Worker)
	{
		return;
	}
	Worker = MakeShared<FRealSenseWorker>(Settings);
	Worker->SetDebugEnabled(bDebugView);
	Worker->Start();
}

void URealSenseSubsystem::StopCamera()
{
	Worker.Reset();
	CachedAnchors[0] = CachedAnchors[1] = FRealSenseHandAnchor();
	bAutoCaptureHandled = false;
}

bool URealSenseSubsystem::IsStreaming() const
{
	return Worker && Worker->IsStreaming();
}

FString URealSenseSubsystem::GetLastError() const
{
	return Worker ? Worker->GetError() : FString();
}

FRealSenseIntrinsics URealSenseSubsystem::GetColorIntrinsics() const
{
	return Worker ? Worker->GetColorIntrinsics() : FRealSenseIntrinsics();
}

FRealSenseHandAnchor URealSenseSubsystem::GetAnchor(int32 PlayerId) const
{
	return (PlayerId == 1 || PlayerId == 2) ? CachedAnchors[PlayerId - 1] : FRealSenseHandAnchor();
}

void URealSenseSubsystem::RequestBackgroundCapture(float DelaySeconds)
{
	if (Worker)
	{
		UE_LOG(LogRealSense, Log, TEXT("Background capture in %.1f s: step out of view"), DelaySeconds);
		Worker->RequestBackground(DelaySeconds);
	}
}

void URealSenseSubsystem::RecaptureBackground()
{
	RequestBackgroundCapture(GetDefault<URealSenseProjectSettings>()->BackgroundCaptureDelayS);
}

float URealSenseSubsystem::GetBackgroundCountdown() const
{
	return Worker ? static_cast<float>(Worker->GetBackgroundCountdown()) : -1.f;
}

void URealSenseSubsystem::Tick(float DeltaTime)
{
	// Without a background every surface in range counts as a player, so learn the empty room
	// as soon as the camera delivers frames (it can take seconds to open)
	if (!bAutoCaptureHandled && Worker->IsStreaming())
	{
		bAutoCaptureHandled = true;
		if (GetDefault<URealSenseProjectSettings>()->bAutoCaptureBackground)
		{
			RecaptureBackground();
		}
	}

	Worker->GetAnchors(CachedAnchors);
	UploadColorFrame();
	if (bDebugView)
	{
		UploadDebugFrame();
	}
}

void URealSenseSubsystem::UploadColorFrame()
{
	if (!Worker->TakeColorFrame(ColorPixels, ColorSeq))
	{
		return;
	}

	const uint32 Width = ColorTexture->GetSizeX();
	const uint32 Height = ColorTexture->GetSizeY();
	if (ColorPixels.Num() != int64(Width) * Height * 4)
	{
		return;
	}

	// The worker refills a fresh buffer meanwhile
	EnqueueUpload(ColorTexture, MoveTemp(ColorPixels));
	ColorPixels.Reset();
}

void URealSenseSubsystem::SetDebugViewEnabled(bool bEnabled)
{
	bDebugView = bEnabled;
	if (Worker)
	{
		Worker->SetDebugEnabled(bEnabled);
	}
}

void URealSenseSubsystem::UploadDebugFrame()
{
	if (!Worker->TakeDebugFrame(DebugPixels, TrackingStats, DebugSeq))
	{
		return;
	}

	const int32 Width = TrackingStats.Width;
	const int32 Height = TrackingStats.Height;
	if (Width <= 0 || Height <= 0 || DebugPixels.Num() != Width * Height * 4)
	{
		return;
	}

	// Sized by the first image: decimation decides the resolution
	if (!DebugTexture || DebugTexture->GetSizeX() != Width || DebugTexture->GetSizeY() != Height)
	{
		DebugTexture = UTexture2D::CreateTransient(Width, Height, PF_B8G8R8A8, TEXT("RealSenseDebug"));
		DebugTexture->Filter = TF_Nearest;
		DebugTexture->NeverStream = true;
		DebugTexture->UpdateResource();
	}

	EnqueueUpload(DebugTexture, MoveTemp(DebugPixels));
	DebugPixels.Reset();
}

ETickableTickType URealSenseSubsystem::GetTickableTickType() const
{
	// The class default object must never tick
	return IsTemplate() ? ETickableTickType::Never : ETickableTickType::Conditional;
}

bool URealSenseSubsystem::IsTickable() const
{
	return Worker.IsValid() && ColorTexture != nullptr;
}

TStatId URealSenseSubsystem::GetStatId() const
{
	RETURN_QUICK_DECLARE_CYCLE_STAT(URealSenseSubsystem, STATGROUP_Tickables);
}
