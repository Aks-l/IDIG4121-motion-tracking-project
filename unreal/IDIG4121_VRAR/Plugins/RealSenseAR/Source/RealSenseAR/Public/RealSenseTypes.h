#pragma once

#include "CoreMinimal.h"
#include "Engine/DeveloperSettings.h"
#include "RealSenseTypes.generated.h"

/** Pinhole model of one RealSense stream, in pixels. */
USTRUCT(BlueprintType)
struct REALSENSEAR_API FRealSenseIntrinsics
{
	GENERATED_BODY()

	UPROPERTY(BlueprintReadOnly, Category = "RealSense")
	int32 Width = 0;

	UPROPERTY(BlueprintReadOnly, Category = "RealSense")
	int32 Height = 0;

	UPROPERTY(BlueprintReadOnly, Category = "RealSense")
	float Fx = 0.f;

	UPROPERTY(BlueprintReadOnly, Category = "RealSense")
	float Fy = 0.f;

	/** Principal point: the pixel the optical axis goes through. */
	UPROPERTY(BlueprintReadOnly, Category = "RealSense")
	float Ppx = 0.f;

	UPROPERTY(BlueprintReadOnly, Category = "RealSense")
	float Ppy = 0.f;

	bool IsValid() const { return Width > 0 && Height > 0 && Fx > 0.f && Fy > 0.f; }
};

/** One player's hand anchor. */
USTRUCT(BlueprintType)
struct REALSENSEAR_API FRealSenseHandAnchor
{
	GENERATED_BODY()

	UPROPERTY(BlueprintReadOnly, Category = "RealSense")
	bool bValid = false;

	/** Held over from an earlier frame because the hand was lost for a moment. */
	UPROPERTY(BlueprintReadOnly, Category = "RealSense")
	bool bStale = false;

	/**
	 * Metres in the RealSense COLOUR camera frame (+X right, +Y down, +Z forward), never mirrored.
	 * Turn it into Unreal world space with ARealSenseMirrorCamera::CameraToWorld.
	 */
	UPROPERTY(BlueprintReadOnly, Category = "RealSense")
	FVector CameraPoint = FVector::ZeroVector;

	/** Pixel in the processed (decimated, screen-oriented) depth image, for debug overlays. */
	UPROPERTY(BlueprintReadOnly, Category = "RealSense")
	FVector2D DepthPixel = FVector2D::ZeroVector;

	UPROPERTY(BlueprintReadOnly, Category = "RealSense")
	double Timestamp = 0.0;
};

UENUM(BlueprintType)
enum class ERealSenseAnchorMode : uint8
{
	/** Each player's point reaching farthest toward the other player. Works side-on and facing the camera. */
	Reach,
	/** Each player's point closest to the camera. Only finds hands held out toward it. */
	Nearest
};

/**
 * Every tunable number of capture and tracking (the C++ twin of coop_game/config.py).
 * Distances in metres (M) or millimetres (Mm) as named.
 */
USTRUCT(BlueprintType)
struct REALSENSEAR_API FRealSenseSettings
{
	GENERATED_BODY()

	// ------------------------------------------------------------ camera

	/** The AR background. 1280x720 matches a 16:9 projector exactly. */
	UPROPERTY(EditAnywhere, Category = "Camera")
	int32 ColorWidth = 1280;

	UPROPERTY(EditAnywhere, Category = "Camera")
	int32 ColorHeight = 720;

	/** The D435's best depth resolution. */
	UPROPERTY(EditAnywhere, Category = "Camera")
	int32 DepthWidth = 848;

	UPROPERTY(EditAnywhere, Category = "Camera")
	int32 DepthHeight = 480;

	UPROPERTY(EditAnywhere, Category = "Camera")
	int32 Fps = 30;

	/** Tracking runs at DepthWidth/Decimation: plenty for two players. */
	UPROPERTY(EditAnywhere, Category = "Camera", meta = (ClampMin = 1, ClampMax = 8))
	int32 Decimation = 2;

	/** Hard depth band, applied by librealsense's threshold filter. */
	UPROPERTY(EditAnywhere, Category = "Camera")
	float NearM = 0.5f;

	UPROPERTY(EditAnywhere, Category = "Camera")
	float FarM = 4.5f;

	/** Spatial smoothing costs ~1 ms; temporal smoothing adds lag, so it's off. */
	UPROPERTY(EditAnywhere, Category = "Camera")
	bool bSpatialFilter = true;

	UPROPERTY(EditAnywhere, Category = "Camera")
	bool bTemporalFilter = false;

	/**
	 * The camera looks out of the screen at the players, so flip it like a mirror:
	 * Player 1 (left on the screen) is also left in the image and in Unreal.
	 */
	UPROPERTY(EditAnywhere, Category = "Camera")
	bool bMirror = true;

	// -------------------------------------------------------- background

	UPROPERTY(EditAnywhere, Category = "Background")
	int32 BackgroundFrames = 45;

	/** A pixel is a player when it is this much closer than the background... */
	UPROPERTY(EditAnywhere, Category = "Background")
	float BgMarginMm = 80.f;

	/** ...or this many times the expected stereo noise there, whichever is more. */
	UPROPERTY(EditAnywhere, Category = "Background")
	float BgNoiseK = 3.f;

	/** Slowly re-learn the background where nobody is (lights, a moved chair). */
	UPROPERTY(EditAnywhere, Category = "Background")
	float BgLearningRate = 0.005f;

	// ----------------------------------------------------------- players

	/** At the processed resolution. */
	UPROPERTY(EditAnywhere, Category = "Players")
	int32 MinPlayerAreaPx = 1200;

	/** The divider between the players is searched in this band of the width. */
	UPROPERTY(EditAnywhere, Category = "Players")
	float SplitSearchMin = 0.25f;

	UPROPERTY(EditAnywhere, Category = "Players")
	float SplitSearchMax = 0.75f;

	/** Moving the divider costs this much per px, so it doesn't jump around. */
	UPROPERTY(EditAnywhere, Category = "Players")
	float SplitStickiness = 0.5f;

	UPROPERTY(EditAnywhere, Category = "Players")
	float SplitSmoothing = 0.3f;

	// ----------------------------------------------------------- anchors

	UPROPERTY(EditAnywhere, Category = "Anchors")
	ERealSenseAnchorMode AnchorMode = ERealSenseAnchorMode::Reach;

	/** Ignore the lowest part of each player (legs, feet) when looking for hands. */
	UPROPERTY(EditAnywhere, Category = "Anchors")
	float IgnoreLowerFraction = 0.35f;

	/** Nearest: the hand is everything within HandBandMm of this depth percentile. */
	UPROPERTY(EditAnywhere, Category = "Anchors")
	float NearestPercentile = 1.f;

	UPROPERTY(EditAnywhere, Category = "Anchors")
	float HandBandMm = 80.f;

	/** Reach: the hand is everything within ReachBandPx of the inner edge. */
	UPROPERTY(EditAnywhere, Category = "Anchors")
	int32 ReachBandPx = 10;

	/** A lost anchor is held this long before it is reported missing. */
	UPROPERTY(EditAnywhere, Category = "Anchors")
	float AnchorHoldS = 0.25f;

	/** 1-euro filter: lower cutoff = less jitter, higher beta = less lag on fast moves. */
	UPROPERTY(EditAnywhere, Category = "Anchors")
	float OneEuroMinCutoff = 1.5f;

	UPROPERTY(EditAnywhere, Category = "Anchors")
	float OneEuroBeta = 8.f;
};

/** Project Settings > Plugins > RealSense AR. */
UCLASS(config = Game, defaultconfig, meta = (DisplayName = "RealSense AR"))
class REALSENSEAR_API URealSenseProjectSettings : public UDeveloperSettings
{
	GENERATED_BODY()

public:
	/** Open the camera as soon as the game starts. */
	UPROPERTY(config, EditAnywhere, Category = "RealSense")
	bool bAutoStart = true;

	/** Learn the empty room automatically as soon as the camera streams. */
	UPROPERTY(config, EditAnywhere, Category = "RealSense")
	bool bAutoCaptureBackground = true;

	/** Countdown before every background capture, so everyone can step out of view. */
	UPROPERTY(config, EditAnywhere, Category = "RealSense", meta = (ClampMin = 0, Units = "s"))
	float BackgroundCaptureDelayS = 3.f;

	UPROPERTY(config, EditAnywhere, Category = "RealSense", meta = (ShowOnlyInnerProperties))
	FRealSenseSettings Settings;

	virtual FName GetCategoryName() const override { return TEXT("Plugins"); }
};
