#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "ZObstacle.generated.h"

class ARealSenseMirrorCamera;
class UPrimitiveComponent;
class UStaticMeshComponent;

/**
 * Beat Saber style: spawns far behind the players and flies straight at the camera (-X in the
 * mirror camera's floor-aligned world), through the space where the couch is carried.
 */
UCLASS()
class IDIG4121_VRAR_API AZObstacle : public AActor
{
	GENERATED_BODY()

public:
	AZObstacle();

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Obstacle")
	TObjectPtr<UStaticMeshComponent> Mesh;

	/** cm/s toward the camera. Set by the spawner. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Obstacle")
	float Speed = 300.f;

	/** Destroyed once this close to the camera plane (it has flown past the players). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Obstacle")
	float DespawnDistanceCm = 40.f;

	UPROPERTY(Transient)
	TObjectPtr<ARealSenseMirrorCamera> MirrorCamera;

	virtual void BeginPlay() override;
	virtual void Tick(float DeltaSeconds) override;

private:
	UFUNCTION()
	void OnOverlap(UPrimitiveComponent* OverlappedComponent, AActor* OtherActor, UPrimitiveComponent* OtherComp,
		int32 OtherBodyIndex, bool bFromSweep, const FHitResult& SweepResult);
};

/** Spawns AZObstacles in the distance at random intervals, faster and faster. */
UCLASS()
class IDIG4121_VRAR_API AObstacleSpawner : public AActor
{
	GENERATED_BODY()

public:
	AObstacleSpawner();

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Spawner")
	TSubclassOf<AZObstacle> ObstacleClass;

	/** Found automatically when left empty. */
	UPROPERTY(EditInstanceOnly, BlueprintReadWrite, Category = "Spawner")
	TObjectPtr<ARealSenseMirrorCamera> MirrorCamera;

	/** How far in front of the camera they appear. The players stand at ~250 cm. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Spawner")
	float SpawnDistanceCm = 900.f;

	/** Sideways spread around the camera axis. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Spawner")
	float HalfWidthCm = 120.f;

	/** Height above the floor: low ones are jumped over (lift the couch), high ones ducked under. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Spawner")
	FVector2D HeightRangeCm = FVector2D(40.f, 170.f);

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Spawner")
	FVector2D SpawnGapS = FVector2D(2.f, 3.4f);

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Spawner")
	float StartSpeed = 300.f;

	/** cm/s faster for every obstacle spawned. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Spawner")
	float SpeedUp = 8.f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Spawner")
	bool bSpawning = true;

	virtual void BeginPlay() override;
	virtual void Tick(float DeltaSeconds) override;

private:
	void Spawn();

	float NextSpawnIn = 0.f;
	int32 Spawned = 0;
};
