#pragma once

#include "CoreMinimal.h"
#include "Camera/CameraActor.h"
#include "Camera/CameraComponent.h"
#include "InputCoreTypes.h"
#include "RealSenseMirrorCamera.generated.h"

class UMaterialInstanceDynamic;
class UMaterialInterface;

/** A camera component that can move its optical axis off the screen centre (the lens's principal point). */
UCLASS(ClassGroup = "RealSense")
class REALSENSEAR_API URealSenseCameraComponent : public UCameraComponent
{
	GENERATED_BODY()

public:
	/** NDC units (the screen spans -1..1). See RealSenseMath::OffCenterProjection. */
	UPROPERTY(VisibleInstanceOnly, Transient, Category = "RealSense")
	FVector2D OffCenterProjectionOffset = FVector2D::ZeroVector;

	virtual void GetCameraView(float DeltaTime, FMinimalViewInfo& DesiredView) override;
};

/**
 * The virtual twin of the physical D435 colour camera, and the AR mirror's view.
 *
 * World layout: the floor is Z = 0 directly below the lens, the camera looks along +X (toward the
 * players), tilted down by CameraPitchDeg. So "toward the camera" is -X and up is +Z, whatever the
 * real tilt is, and obstacles and physics can work in a level, floor-aligned world.
 *
 * Once the camera streams, it copies the lens's FOV, aspect and principal point onto the view and
 * binds the live video to the AR background post-process material.
 */
UCLASS()
class REALSENSEAR_API ARealSenseMirrorCamera : public ACameraActor
{
	GENERATED_BODY()

public:
	ARealSenseMirrorCamera(const FObjectInitializer& ObjectInitializer);

	/** Height of the lens above the floor: measure it. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "RealSense|Placement")
	float CameraHeightM = 2.2f;

	/** How far the camera is tilted down. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "RealSense|Placement")
	float CameraPitchDeg = 15.f;

	/** Place the actor from the two numbers above at BeginPlay, instead of where it sits in the level. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "RealSense|Placement")
	bool bApplyPhysicalPlacement = true;

	/**
	 * Post-process material (Scene Color After Tonemapping) that shows the video wherever no
	 * virtual geometry was drawn. Parameters: Texture "Video", Scalar "Mirror".
	 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "RealSense|Background")
	TObjectPtr<UMaterialInterface> BackgroundMaterial;

	/** Press to learn the empty room again, e.g. after moving furniture or the camera. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "RealSense|Background")
	FKey RecaptureBackgroundKey = EKeys::B;

	/** Draw the two tracked anchors as spheres: they should sit on the players' hands in the video. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "RealSense|Debug")
	bool bDrawAnchors = false;

	/** On-screen lines for the capture countdown and camera errors (development builds only). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "RealSense|Debug")
	bool bShowStatus = true;

	/**
	 * RealSense colour-camera point (metres, from FRealSenseHandAnchor::CameraPoint) -> Unreal world (cm).
	 * This is the one function gameplay needs to put things on the players' hands.
	 */
	UFUNCTION(BlueprintPure, Category = "RealSense")
	FVector CameraToWorld(const FVector& CameraPointMetres) const;

	/** Player 1 / 2 hand in world space. False when that hand isn't tracked. */
	UFUNCTION(BlueprintPure, Category = "RealSense")
	bool GetHandWorldLocation(int32 PlayerId, FVector& OutLocation) const;

	virtual void BeginPlay() override;
	virtual void Tick(float DeltaSeconds) override;

private:
	void ApplyIntrinsics();
	void RecaptureBackground();
	void ShowStatus() const;

	UPROPERTY(Transient)
	TObjectPtr<UMaterialInstanceDynamic> BackgroundMID;

	bool bIntrinsicsApplied = false;
	bool bMirror = true;
};
