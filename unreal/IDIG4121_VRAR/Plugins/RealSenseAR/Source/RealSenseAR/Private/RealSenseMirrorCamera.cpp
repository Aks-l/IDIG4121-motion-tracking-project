#include "RealSenseMirrorCamera.h"

#include "Components/InputComponent.h"
#include "DrawDebugHelpers.h"
#include "Engine/Engine.h"
#include "Engine/GameInstance.h"
#include "Engine/World.h"
#include "GameFramework/PlayerController.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "RealSenseAR.h"
#include "RealSenseMath.h"
#include "RealSenseSubsystem.h"

void URealSenseCameraComponent::GetCameraView(float DeltaTime, FMinimalViewInfo& DesiredView)
{
	Super::GetCameraView(DeltaTime, DesiredView);
	DesiredView.OffCenterProjectionOffset = OffCenterProjectionOffset;
}

ARealSenseMirrorCamera::ARealSenseMirrorCamera(const FObjectInitializer& ObjectInitializer)
	: Super(ObjectInitializer.SetDefaultSubobjectClass<URealSenseCameraComponent>(TEXT("CameraComponent")))
{
	PrimaryActorTick.bCanEverTick = true;

	UCameraComponent* Camera = GetCameraComponent();
	// The projection must match the video exactly: letterbox rather than stretch
	Camera->bConstrainAspectRatio = true;
	Camera->AspectRatio = 16.f / 9.f;

	// Virtual objects sit over a real video: no eye adaptation, no motion blur smearing them
	FPostProcessSettings& PP = Camera->PostProcessSettings;
	PP.bOverride_AutoExposureMethod = true;
	PP.AutoExposureMethod = AEM_Manual;
	PP.bOverride_AutoExposureApplyPhysicalCameraExposure = true;
	PP.AutoExposureApplyPhysicalCameraExposure = false;
	PP.bOverride_AutoExposureBias = true;
	PP.AutoExposureBias = 0.f;
	PP.bOverride_MotionBlurAmount = true;
	PP.MotionBlurAmount = 0.f;
}

void ARealSenseMirrorCamera::BeginPlay()
{
	Super::BeginPlay();

	if (bApplyPhysicalPlacement)
	{
		SetActorLocationAndRotation(FVector(0.0, 0.0, CameraHeightM * RealSenseMath::MetresToUnreal), FRotator(-CameraPitchDeg, 0.0, 0.0));
	}

	// Become the view of the first local player without a level blueprint, and take its key presses
	if (APlayerController* Player = GetWorld()->GetFirstPlayerController())
	{
		Player->SetViewTarget(this);
		EnableInput(Player);
		InputComponent->BindKey(RecaptureBackgroundKey, IE_Pressed, this, &ARealSenseMirrorCamera::RecaptureBackground);
	}

	URealSenseSubsystem* RealSense = GetGameInstance()->GetSubsystem<URealSenseSubsystem>();
	bMirror = RealSense->GetSettings().bMirror;

	if (BackgroundMaterial)
	{
		BackgroundMID = UMaterialInstanceDynamic::Create(BackgroundMaterial, this);
		BackgroundMID->SetTextureParameterValue(TEXT("Video"), RealSense->GetColorTexture());
		BackgroundMID->SetScalarParameterValue(TEXT("Mirror"), bMirror ? 1.f : 0.f);
		GetCameraComponent()->PostProcessSettings.AddBlendable(BackgroundMID, 1.f);
	}
	else
	{
		UE_LOG(LogRealSense, Warning, TEXT("%s has no BackgroundMaterial: the video will not be shown"), *GetName());
	}
}

void ARealSenseMirrorCamera::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);

	// The lens is only known once the worker thread has opened the camera
	if (!bIntrinsicsApplied)
	{
		ApplyIntrinsics();
	}

	if (bShowStatus)
	{
		ShowStatus();
	}

	if (bDrawAnchors)
	{
		const FColor Colors[2] = { FColor(40, 140, 255), FColor(60, 200, 60) };
		for (int32 PlayerId = 1; PlayerId <= 2; ++PlayerId)
		{
			FVector Hand;
			if (GetHandWorldLocation(PlayerId, Hand))
			{
				DrawDebugSphere(GetWorld(), Hand, 6.f, 12, Colors[PlayerId - 1], false, -1.f, 0, 1.5f);
			}
		}
	}
}

void ARealSenseMirrorCamera::RecaptureBackground()
{
	GetGameInstance()->GetSubsystem<URealSenseSubsystem>()->RecaptureBackground();
}

void ARealSenseMirrorCamera::ShowStatus() const
{
	if (!GEngine)
	{
		return;
	}

	// One fixed message slot, rewritten every frame, so lines never pile up
	const uint64 Slot = GetUniqueID();
	const URealSenseSubsystem* RealSense = GetGameInstance()->GetSubsystem<URealSenseSubsystem>();
	const FString Error = RealSense->GetLastError();
	const float Countdown = RealSense->GetBackgroundCountdown();

	if (!Error.IsEmpty())
	{
		GEngine->AddOnScreenDebugMessage(Slot, 0.5f, FColor::Red, FString::Printf(TEXT("RealSense: %s"), *Error));
	}
	else if (!RealSense->IsStreaming())
	{
		GEngine->AddOnScreenDebugMessage(Slot, 0.5f, FColor::White, TEXT("RealSense: opening camera..."));
	}
	else if (Countdown > 0.f)
	{
		GEngine->AddOnScreenDebugMessage(Slot, 0.5f, FColor::Yellow, FString::Printf(
			TEXT("Step out of view: learning the empty room in %d"), FMath::CeilToInt(Countdown)));
	}
	else if (Countdown == 0.f)
	{
		GEngine->AddOnScreenDebugMessage(Slot, 0.5f, FColor::Yellow, TEXT("Learning the empty room... stay out of view"));
	}
	else
	{
		// Captured: clear the slot
		GEngine->RemoveOnScreenDebugMessage(Slot);
	}
}

void ARealSenseMirrorCamera::ApplyIntrinsics()
{
	const FRealSenseIntrinsics Intrinsics = GetGameInstance()->GetSubsystem<URealSenseSubsystem>()->GetColorIntrinsics();
	if (!Intrinsics.IsValid())
	{
		return;
	}

	URealSenseCameraComponent* Camera = CastChecked<URealSenseCameraComponent>(GetCameraComponent());
	Camera->SetFieldOfView(RealSenseMath::HorizontalFOVDegrees(Intrinsics));
	Camera->SetAspectRatio(float(Intrinsics.Width) / Intrinsics.Height);
	Camera->OffCenterProjectionOffset = RealSenseMath::OffCenterProjection(Intrinsics, bMirror);
	bIntrinsicsApplied = true;

	UE_LOG(LogRealSense, Log, TEXT("Mirror camera: HFOV %.2f deg, aspect %.4f, principal point offset (%.4f, %.4f)"),
		Camera->FieldOfView, Camera->AspectRatio, Camera->OffCenterProjectionOffset.X, Camera->OffCenterProjectionOffset.Y);
}

FVector ARealSenseMirrorCamera::CameraToWorld(const FVector& CameraPointMetres) const
{
	// Camera-local cm, then through the camera's pose (height + tilt) into the floor-aligned world
	const FVector Local = RealSenseMath::CameraToUnrealLocal(CameraPointMetres, bMirror);
	return GetCameraComponent()->GetComponentTransform().TransformPosition(Local);
}

bool ARealSenseMirrorCamera::GetHandWorldLocation(int32 PlayerId, FVector& OutLocation) const
{
	const FRealSenseHandAnchor Anchor = GetGameInstance()->GetSubsystem<URealSenseSubsystem>()->GetAnchor(PlayerId);
	if (!Anchor.bValid)
	{
		return false;
	}
	OutLocation = CameraToWorld(Anchor.CameraPoint);
	return true;
}
