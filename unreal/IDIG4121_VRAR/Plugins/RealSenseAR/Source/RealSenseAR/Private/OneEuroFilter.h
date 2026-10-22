#pragma once

#include "CoreMinimal.h"

/** 1-euro filter (Casiez et al. 2012): smooths hard when still, follows fast moves. Per component. */
struct FOneEuroFilter
{
	float MinCutoff = 1.5f;
	float Beta = 8.f;
	float DCutoff = 1.f;

	FOneEuroFilter() = default;
	FOneEuroFilter(float InMinCutoff, float InBeta) : MinCutoff(InMinCutoff), Beta(InBeta) {}

	void Reset()
	{
		Value.Reset();
		Speed = FVector::ZeroVector;
	}

	FVector Filter(const FVector& In, double Timestamp)
	{
		if (!Value.IsSet())
		{
			Value = In;
			Time = Timestamp;
			return In;
		}

		const double Dt = FMath::Max(Timestamp - Time, 1e-3);
		Time = Timestamp;

		const FVector RawSpeed = (In - *Value) / Dt;
		Speed += Alpha(DCutoff, Dt) * (RawSpeed - Speed);

		FVector Out;
		for (int32 Axis = 0; Axis < 3; ++Axis)
		{
			const double Cutoff = MinCutoff + Beta * FMath::Abs(Speed[Axis]);
			Out[Axis] = (*Value)[Axis] + Alpha(Cutoff, Dt) * (In[Axis] - (*Value)[Axis]);
		}
		Value = Out;
		return Out;
	}

private:
	static double Alpha(double Cutoff, double Dt)
	{
		const double Tau = 1.0 / (2.0 * UE_DOUBLE_PI * Cutoff);
		return 1.0 / (1.0 + Tau / Dt);
	}

	TOptional<FVector> Value;
	FVector Speed = FVector::ZeroVector;
	double Time = 0.0;
};
