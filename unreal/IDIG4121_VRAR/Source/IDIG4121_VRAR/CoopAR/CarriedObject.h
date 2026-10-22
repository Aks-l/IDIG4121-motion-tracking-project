#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "CarriedObject.generated.h"

class ARealSenseMirrorCamera;
class UStaticMeshComponent;

DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(FOnCarriedObjectHit, AActor*, Obstacle);
DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(FOnGripChanged, bool, bHeld);

/**
 * The shared object (the couch) as a rigid bar between the players' hands: Player 1 holds the
 * left end, Player 2 the right. Held, it springs toward the line between the hands:
 *   centre   = midpoint of the hands
 *   yaw      = one hand nearer the camera than the other
 *   roll     = one hand higher than the other
 *   pitch    = the twist about the bar, which two points can't see: kept seat-up
 * Dropped, it falls under physics until both hands come back to its ends.
 *
 * Model the mesh with its LENGTH ALONG LOCAL +Y, seat up (+Z), front facing the camera (-X).
 */
UCLASS()
class IDIG4121_VRAR_API ACarriedObject : public AActor
{
	GENERATED_BODY()

public:
	ACarriedObject();

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Carry")
	TObjectPtr<UStaticMeshComponent> Mesh;

	/** Found automatically when left empty. */
	UPROPERTY(EditInstanceOnly, BlueprintReadWrite, Category = "Carry")
	TObjectPtr<ARealSenseMirrorCamera> MirrorCamera;

	/** End to end, cm: the hands hold the ends. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Carry")
	float LengthCm = 160.f;

	/** Heavier follows the hands more slowly. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Carry")
	float Mass = 1.f;

	/** Natural frequency (1/s) of the follow spring at mass 1. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Carry")
	float Responsiveness = 14.f;

	/** 1 = no overshoot, lower = wobblier. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Carry")
	float DampingRatio = 0.8f;

	/** Held while the hands are at most (1 + this) x length apart. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Carry")
	float GripTolerance = 0.4f;

	/** A hand may vanish this long before the players lose their grip. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Carry")
	float GripGraceS = 0.35f;

	/** Hands this close to the ends of a dropped object pick it up again. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Carry")
	float RegrabRadiusCm = 35.f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Carry")
	float HitCooldownS = 1.f;

	UPROPERTY(BlueprintAssignable, Category = "Carry")
	FOnCarriedObjectHit OnObstacleHit;

	UPROPERTY(BlueprintAssignable, Category = "Carry")
	FOnGripChanged OnGripChanged;

	UFUNCTION(BlueprintPure, Category = "Carry")
	bool IsHeld() const { return bHeld; }

	/** Called by obstacles that touch it. Applies the hit cooldown. */
	void NotifyObstacleHit(AActor* Obstacle);

	virtual void BeginPlay() override;
	virtual void Tick(float DeltaSeconds) override;

private:
	void SetHeld(bool bNewHeld);
	void FollowHands(const FVector& Left, const FVector& Right, float DeltaSeconds);

	bool bHeld = false;
	FVector Velocity = FVector::ZeroVector;
	double LastSeenBothHands = -1.0;
	double LastHitTime = -1.0e9;
};
