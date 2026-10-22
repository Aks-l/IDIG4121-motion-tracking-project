#include "ZObstacle.h"

#include "CarriedObject.h"
#include "Components/StaticMeshComponent.h"
#include "EngineUtils.h"
#include "RealSenseMirrorCamera.h"

namespace
{
	/** The camera's forward direction, flattened onto the floor: "away from the camera". */
	FVector FloorForward(const AActor* Camera)
	{
		return Camera->GetActorForwardVector().GetSafeNormal2D();
	}
}

AZObstacle::AZObstacle()
{
	PrimaryActorTick.bCanEverTick = true;

	Mesh = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("Mesh"));
	Mesh->SetCollisionProfileName(TEXT("OverlapAllDynamic"));
	Mesh->SetGenerateOverlapEvents(true);
	RootComponent = Mesh;
}

void AZObstacle::BeginPlay()
{
	Super::BeginPlay();
	Mesh->OnComponentBeginOverlap.AddDynamic(this, &AZObstacle::OnOverlap);

	if (!MirrorCamera)
	{
		TActorIterator<ARealSenseMirrorCamera> It(GetWorld());
		MirrorCamera = It ? *It : nullptr;
	}
}

void AZObstacle::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	if (!MirrorCamera)
	{
		Destroy();
		return;
	}

	const FVector Forward = FloorForward(MirrorCamera);
	AddActorWorldOffset(-Forward * Speed * DeltaSeconds);

	// Distance in front of the camera, measured along the floor
	const float Ahead = FVector::DotProduct(GetActorLocation() - MirrorCamera->GetActorLocation(), Forward);
	if (Ahead < DespawnDistanceCm)
	{
		Destroy();
	}
}

void AZObstacle::OnOverlap(UPrimitiveComponent* OverlappedComponent, AActor* OtherActor, UPrimitiveComponent* OtherComp,
	int32 OtherBodyIndex, bool bFromSweep, const FHitResult& SweepResult)
{
	if (ACarriedObject* Carried = Cast<ACarriedObject>(OtherActor))
	{
		Carried->NotifyObstacleHit(this);
	}
}

AObstacleSpawner::AObstacleSpawner()
{
	PrimaryActorTick.bCanEverTick = true;
	ObstacleClass = AZObstacle::StaticClass();
}

void AObstacleSpawner::BeginPlay()
{
	Super::BeginPlay();

	if (!MirrorCamera)
	{
		TActorIterator<ARealSenseMirrorCamera> It(GetWorld());
		MirrorCamera = It ? *It : nullptr;
	}
	NextSpawnIn = FMath::FRandRange(SpawnGapS.X, SpawnGapS.Y);
}

void AObstacleSpawner::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	if (!bSpawning || !MirrorCamera || !ObstacleClass)
	{
		return;
	}

	NextSpawnIn -= DeltaSeconds;
	if (NextSpawnIn <= 0.f)
	{
		Spawn();
		NextSpawnIn = FMath::FRandRange(SpawnGapS.X, SpawnGapS.Y);
	}
}

void AObstacleSpawner::Spawn()
{
	const FVector Forward = FloorForward(MirrorCamera);
	const FVector Right = FVector::CrossProduct(FVector::UpVector, Forward);
	const FVector CameraOnFloor(MirrorCamera->GetActorLocation().X, MirrorCamera->GetActorLocation().Y, 0.0);

	const FVector Location = CameraOnFloor
		+ Forward * SpawnDistanceCm
		+ Right * FMath::FRandRange(-HalfWidthCm, HalfWidthCm)
		+ FVector::UpVector * FMath::FRandRange(HeightRangeCm.X, HeightRangeCm.Y);
	const FRotator Facing = (-Forward).Rotation();

	FActorSpawnParameters Params;
	Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
	AZObstacle* Obstacle = GetWorld()->SpawnActor<AZObstacle>(ObstacleClass, Location, Facing, Params);
	if (!Obstacle)
	{
		return;
	}

	Obstacle->MirrorCamera = MirrorCamera;
	Obstacle->Speed = StartSpeed + SpeedUp * Spawned++;
}
