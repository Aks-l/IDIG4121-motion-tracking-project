#include "CarriedObject.h"

#include "Components/StaticMeshComponent.h"
#include "EngineUtils.h"
#include "RealSenseMirrorCamera.h"

ACarriedObject::ACarriedObject()
{
	PrimaryActorTick.bCanEverTick = true;
	// After the subsystem has cached this frame's anchors
	PrimaryActorTick.TickGroup = TG_PrePhysics;

	Mesh = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("Mesh"));
	Mesh->SetCollisionProfileName(TEXT("PhysicsActor"));
	Mesh->SetGenerateOverlapEvents(true);
	RootComponent = Mesh;
}

void ACarriedObject::BeginPlay()
{
	Super::BeginPlay();

	if (!MirrorCamera)
	{
		TActorIterator<ARealSenseMirrorCamera> It(GetWorld());
		MirrorCamera = It ? *It : nullptr;
	}

	// Starts dropped: a rigid body resting on the floor until both hands reach its ends
	bHeld = false;
	Mesh->SetSimulatePhysics(true);
}

void ACarriedObject::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	if (!MirrorCamera)
	{
		return;
	}

	const double Now = GetWorld()->GetTimeSeconds();
	FVector Left, Right;
	const bool bBothHands = MirrorCamera->GetHandWorldLocation(1, Left) && MirrorCamera->GetHandWorldLocation(2, Right);

	if (!bBothHands)
	{
		if (bHeld && Now - LastSeenBothHands > GripGraceS)
		{
			SetHeld(false);
		}
		return;
	}
	LastSeenBothHands = Now;

	const float Span = FVector::Dist(Left, Right);
	if (bHeld)
	{
		if (Span > LengthCm * (1.f + GripTolerance))
		{
			// Pulled apart: it slips out
			SetHeld(false);
			return;
		}
		FollowHands(Left, Right, DeltaSeconds);
	}
	else
	{
		// Pick it up again when each hand is near "its" end
		const FVector HalfAxis = GetActorRightVector() * (LengthCm * 0.5f);
		const FVector Centre = GetActorLocation();
		const bool bLeftNear = FVector::Dist(Left, Centre - HalfAxis) <= RegrabRadiusCm;
		const bool bRightNear = FVector::Dist(Right, Centre + HalfAxis) <= RegrabRadiusCm;
		if (bLeftNear && bRightNear)
		{
			SetHeld(true);
		}
	}
}

void ACarriedObject::FollowHands(const FVector& Left, const FVector& Right, float DeltaSeconds)
{
	const FVector TargetCentre = 0.5f * (Left + Right);
	// Length along +Y (Player 1 -> Player 2), keep the seat as close to world-up as the bar allows
	const FQuat TargetRotation = FRotationMatrix::MakeFromYZ(Right - Left, FVector::UpVector).ToQuat();

	// Damped spring on the centre: heavier = slower, DampingRatio < 1 = a little wobble
	const float Omega = Responsiveness / FMath::Sqrt(FMath::Max(Mass, 0.01f));
	const FVector Position = GetActorLocation();
	const FVector Acceleration = Omega * Omega * (TargetCentre - Position) - 2.f * DampingRatio * Omega * Velocity;
	Velocity += Acceleration * DeltaSeconds;
	const FVector NewPosition = Position + Velocity * DeltaSeconds;

	// Rotation follows with the same time constant
	const float Blend = 1.f - FMath::Exp(-Omega * DeltaSeconds);
	const FQuat NewRotation = FQuat::Slerp(GetActorQuat(), TargetRotation, Blend);

	SetActorLocationAndRotation(NewPosition, NewRotation, false, nullptr, ETeleportType::TeleportPhysics);
}

void ACarriedObject::SetHeld(bool bNewHeld)
{
	if (bNewHeld == bHeld)
	{
		return;
	}
	bHeld = bNewHeld;

	// Held: driven kinematically by the hands. Dropped: a real rigid body that falls and settles.
	Mesh->SetSimulatePhysics(!bHeld);
	if (bHeld)
	{
		Velocity = FVector::ZeroVector;
	}
	OnGripChanged.Broadcast(bHeld);
}

void ACarriedObject::NotifyObstacleHit(AActor* Obstacle)
{
	const double Now = GetWorld()->GetTimeSeconds();
	if (Now - LastHitTime < HitCooldownS)
	{
		return;
	}
	LastHitTime = Now;
	OnObstacleHit.Broadcast(Obstacle);
}
