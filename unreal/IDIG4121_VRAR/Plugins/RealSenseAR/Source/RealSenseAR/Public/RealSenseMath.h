#pragma once

#include "CoreMinimal.h"
#include "RealSenseTypes.h"

/**
 * RealSense camera space <-> Unreal.
 *
 * The trick that makes the overlay line up: the Unreal camera IS the RealSense colour camera.
 * Same optical centre (actor origin), same field of view, same principal point, same aspect.
 * Then a virtual object placed at a hand's 3D position projects onto exactly the pixel where the
 * video shows that hand, by construction. Depth error only changes how big it looks, not where.
 *
 *   RealSense (right-handed, metres):  +X right, +Y down, +Z forward (out of the lens)
 *   Unreal    (left-handed, cm):       +X forward, +Y right, +Z up
 */
namespace RealSenseMath
{
	constexpr double MetresToUnreal = 100.0;

	/**
	 * RealSense camera point -> the Unreal camera's local space.
	 * The axis swap has determinant -1, which is exactly the right- to left-handed flip.
	 * Mirroring negates Y as well, matching the horizontally flipped video.
	 */
	FORCEINLINE FVector CameraToUnrealLocal(const FVector& CameraPointMetres, bool bMirror)
	{
		const double Right = bMirror ? -CameraPointMetres.X : CameraPointMetres.X;
		return FVector(CameraPointMetres.Z, Right, -CameraPointMetres.Y) * MetresToUnreal;
	}

	/** The inverse, for checks: Unreal camera-local cm -> RealSense metres. */
	FORCEINLINE FVector UnrealLocalToCamera(const FVector& Local, bool bMirror)
	{
		const FVector M = Local / MetresToUnreal;
		return FVector(bMirror ? -M.Y : M.Y, -M.Z, M.X);
	}

	/** UCameraComponent::FieldOfView is horizontal, in degrees: 2 atan(W / 2 fx). */
	FORCEINLINE float HorizontalFOVDegrees(const FRealSenseIntrinsics& I)
	{
		return FMath::RadiansToDegrees(2.0 * FMath::Atan(I.Width / (2.0 * I.Fx)));
	}

	/**
	 * FMinimalViewInfo::OffCenterProjectionOffset (NDC units: the screen spans -1..1) that moves the
	 * optical axis off the screen centre onto the principal point. NDC y is up, pixel v is down.
	 * The D435 colour principal point is a few pixels off centre: small, but it is free accuracy.
	 */
	FORCEINLINE FVector2D OffCenterProjection(const FRealSenseIntrinsics& I, bool bMirror)
	{
		const double X = 1.0 - 2.0 * (I.Ppx + 0.5) / I.Width;
		const double Y = 2.0 * (I.Ppy + 0.5) / I.Height - 1.0;
		return FVector2D(bMirror ? -X : X, Y);
	}

	/** Where a RealSense camera point lands in the (unmirrored) colour image. For debugging alignment. */
	FORCEINLINE FVector2D ProjectToColorPixel(const FRealSenseIntrinsics& I, const FVector& CameraPointMetres)
	{
		const double Z = FMath::Max(CameraPointMetres.Z, 1e-6);
		return FVector2D(CameraPointMetres.X / Z * I.Fx + I.Ppx, CameraPointMetres.Y / Z * I.Fy + I.Ppy);
	}
}
