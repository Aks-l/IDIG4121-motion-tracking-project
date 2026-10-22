#include "PlayerTracker.h"

#include <algorithm>

#include "PreOpenCVHeaders.h"
#include <opencv2/imgproc.hpp>
#include "PostOpenCVHeaders.h"

namespace
{
	// D435 stereo noise grows with distance squared (Intel tuning guide):
	// rms_mm = z_mm^2 * subpixel / (fx_px * baseline_mm)
	constexpr float Subpixel = 0.08f;
	constexpr float BaselineMm = 50.f;

	/** Nearest-rank percentile; reorders Values. */
	float Percentile(TArray<float>& Values, float Pct)
	{
		const int32 K = FMath::Clamp(FMath::RoundToInt((Values.Num() - 1) * Pct / 100.f), 0, Values.Num() - 1);
		std::nth_element(Values.GetData(), Values.GetData() + K, Values.GetData() + Values.Num());
		return Values[K];
	}

	cv::Mat CleanMask(const cv::Mat& Foreground)
	{
		// Built on first use, not at static init: on Windows the OpenCV DLL is delay-loaded
		static const cv::Mat CloseKernel = cv::getStructuringElement(cv::MORPH_ELLIPSE, cv::Size(5, 5));
		static const cv::Mat OpenKernel = cv::getStructuringElement(cv::MORPH_ELLIPSE, cv::Size(3, 3));

		// Close before open: opening first eats every pixel next to a depth hole
		cv::Mat Mask;
		cv::morphologyEx(Foreground, Mask, cv::MORPH_CLOSE, CloseKernel);
		cv::morphologyEx(Mask, Mask, cv::MORPH_OPEN, OpenKernel);
		return Mask;
	}
}

FPlayerTracker::FPlayerTracker(const FRealSenseSettings& InSettings)
	: Settings(InSettings)
{
}

void FPlayerTracker::CaptureBackground(const TArray<cv::Mat>& Frames, float FxFull)
{
	if (Frames.IsEmpty())
	{
		return;
	}

	const int32 Rows = Frames[0].rows;
	const int32 Cols = Frames[0].cols;
	BgDepth = cv::Mat::zeros(Rows, Cols, CV_32F);
	BgMargin = cv::Mat(Rows, Cols, CV_32F);

	// Per-pixel median of the valid (non-zero) samples
	TArray<float> Samples;
	Samples.Reserve(Frames.Num());
	for (int32 Y = 0; Y < Rows; ++Y)
	{
		for (int32 X = 0; X < Cols; ++X)
		{
			Samples.Reset();
			for (const cv::Mat& Frame : Frames)
			{
				const float D = Frame.at<float>(Y, X);
				if (D > 0.f)
				{
					Samples.Add(D);
				}
			}

			const float Median = Samples.IsEmpty() ? 0.f : Percentile(Samples, 50.f);
			const float Noise = Median * Median * Subpixel / (FxFull * BaselineMm);
			BgDepth.at<float>(Y, X) = Median;
			BgMargin.at<float>(Y, X) = FMath::Max(Settings.BgMarginMm, Settings.BgNoiseK * Noise);
		}
	}
}

cv::Mat FPlayerTracker::Foreground(const cv::Mat& DepthMm) const
{
	cv::Mat Valid = DepthMm > 0.f;

	// No background yet: only the camera's depth band applies
	if (!HasBackground())
	{
		return Valid;
	}

	// Nothing was there when empty, so anything there now is new
	cv::Mat NothingBehind = BgDepth <= 0.f;
	cv::Mat InFront = DepthMm < (BgDepth - BgMargin);
	return Valid & (NothingBehind | InFront);
}

void FPlayerTracker::UpdateBackground(const cv::Mat& DepthMm, const cv::Mat& Occupied)
{
	if (!HasBackground())
	{
		return;
	}

	// Learn only well away from the players, so they never fade in
	static const cv::Mat LearnGuard = cv::Mat::ones(9, 9, CV_8U);
	cv::Mat NearPlayers;
	cv::dilate(Occupied, NearPlayers, LearnGuard);
	cv::Mat Learn = (NearPlayers == 0) & (DepthMm > 0.f) & (BgDepth > 0.f);
	cv::accumulateWeighted(DepthMm, BgDepth, Settings.BgLearningRate, Learn);
}

int32 FPlayerTracker::FindSplit(const cv::Mat& Mask) const
{
	// Column dividing the players: the emptiest column near the middle
	cv::Mat Columns;
	cv::reduce(Mask, Columns, 0, cv::REDUCE_SUM, CV_32F);
	cv::blur(Columns, Columns, cv::Size(9, 1), cv::Point(-1, -1), cv::BORDER_CONSTANT);

	const int32 Width = Mask.cols;
	const int32 Low = FMath::FloorToInt(Width * Settings.SplitSearchMin);
	const int32 High = FMath::FloorToInt(Width * Settings.SplitSearchMax);

	int32 Best = Low;
	float BestCost = TNumericLimits<float>::Max();
	for (int32 X = Low; X < High; ++X)
	{
		float Cost = Columns.at<float>(0, X) / 255.f;
		// Staying put is cheaper than moving, so the divider doesn't jump
		if (SmoothedSplit.IsSet())
		{
			Cost += Settings.SplitStickiness * FMath::Abs(X - *SmoothedSplit);
		}
		if (Cost < BestCost)
		{
			BestCost = Cost;
			Best = X;
		}
	}
	return Best;
}

cv::Mat FPlayerTracker::LargestRegion(const cv::Mat& Mask) const
{
	cv::Mat Labels, Stats, Centroids;
	const int32 Count = cv::connectedComponentsWithStats(Mask, Labels, Stats, Centroids, 8, CV_32S);
	if (Count < 2)
	{
		return cv::Mat();
	}

	int32 Best = 1;
	for (int32 Label = 2; Label < Count; ++Label)
	{
		if (Stats.at<int32>(Label, cv::CC_STAT_AREA) > Stats.at<int32>(Best, cv::CC_STAT_AREA))
		{
			Best = Label;
		}
	}
	if (Stats.at<int32>(Best, cv::CC_STAT_AREA) < Settings.MinPlayerAreaPx)
	{
		return cv::Mat();
	}
	return Labels == Best;
}

cv::Mat FPlayerTracker::UpperBody(const cv::Mat& Player) const
{
	// Hands are never in the lowest part of the body (legs, feet)
	cv::Mat RowMax;
	cv::reduce(Player, RowMax, 1, cv::REDUCE_MAX);

	int32 Top = -1, Bottom = -1;
	for (int32 Y = 0; Y < RowMax.rows; ++Y)
	{
		if (RowMax.at<uint8>(Y, 0))
		{
			Top = Top < 0 ? Y : Top;
			Bottom = Y;
		}
	}

	cv::Mat Upper = Player.clone();
	if (Top < 0)
	{
		return Upper;
	}

	const int32 Cutoff = Top + FMath::FloorToInt((1.f - Settings.IgnoreLowerFraction) * (Bottom - Top));
	if (Cutoff + 1 < Upper.rows)
	{
		Upper.rowRange(Cutoff + 1, Upper.rows).setTo(0);
	}
	return Upper;
}

TOptional<FPlayerTracker::FAnchorPixel> FPlayerTracker::CentreOfLargest(const cv::Mat& Candidates, const cv::Mat& DepthMm)
{
	cv::Mat Labels, Stats, Centroids;
	const int32 Count = cv::connectedComponentsWithStats(Candidates, Labels, Stats, Centroids, 8, CV_32S);
	if (Count < 2)
	{
		return {};
	}

	int32 Best = 1;
	for (int32 Label = 2; Label < Count; ++Label)
	{
		if (Stats.at<int32>(Label, cv::CC_STAT_AREA) > Stats.at<int32>(Best, cv::CC_STAT_AREA))
		{
			Best = Label;
		}
	}

	// Median depth of the region (it is small: a hand)
	const cv::Rect Box(Stats.at<int32>(Best, cv::CC_STAT_LEFT), Stats.at<int32>(Best, cv::CC_STAT_TOP),
		Stats.at<int32>(Best, cv::CC_STAT_WIDTH), Stats.at<int32>(Best, cv::CC_STAT_HEIGHT));
	TArray<float> Depths;
	for (int32 Y = Box.y; Y < Box.y + Box.height; ++Y)
	{
		for (int32 X = Box.x; X < Box.x + Box.width; ++X)
		{
			const float D = DepthMm.at<float>(Y, X);
			if (Labels.at<int32>(Y, X) == Best && D > 0.f)
			{
				Depths.Add(D);
			}
		}
	}
	if (Depths.IsEmpty())
	{
		return {};
	}

	FAnchorPixel Anchor;
	Anchor.U = static_cast<float>(Centroids.at<double>(Best, 0));
	Anchor.V = static_cast<float>(Centroids.at<double>(Best, 1));
	Anchor.DepthMm = Percentile(Depths, 50.f);
	return Anchor;
}

TOptional<FPlayerTracker::FAnchorPixel> FPlayerTracker::NearestAnchor(const cv::Mat& Player, const cv::Mat& DepthMm) const
{
	// The player's surface closest to the camera (a hand held toward it)
	cv::Mat Region = UpperBody(Player) & (DepthMm > 0.f);

	TArray<float> Depths;
	for (int32 Y = 0; Y < Region.rows; ++Y)
	{
		for (int32 X = 0; X < Region.cols; ++X)
		{
			if (Region.at<uint8>(Y, X))
			{
				Depths.Add(DepthMm.at<float>(Y, X));
			}
		}
	}
	if (Depths.IsEmpty())
	{
		return {};
	}

	// A low percentile, not the minimum: single noisy pixels can't win
	const float Nearest = Percentile(Depths, Settings.NearestPercentile);
	cv::Mat Hand = Region & (DepthMm <= Nearest + Settings.HandBandMm);
	return CentreOfLargest(Hand, DepthMm);
}

TOptional<FPlayerTracker::FAnchorPixel> FPlayerTracker::ReachAnchor(const cv::Mat& Player, const cv::Mat& DepthMm, bool bTowardRight) const
{
	// The player's point reaching farthest toward the other player
	cv::Mat Region = UpperBody(Player) & (DepthMm > 0.f);

	std::vector<cv::Point> Points;
	cv::findNonZero(Region, Points);
	if (Points.empty())
	{
		return {};
	}

	TArray<float> Xs;
	Xs.Reserve(Points.size());
	for (const cv::Point& P : Points)
	{
		Xs.Add(static_cast<float>(P.x));
	}

	cv::Mat Band = Region.clone();
	if (bTowardRight)
	{
		const float Edge = Percentile(Xs, 99.f);
		const int32 FirstCol = FMath::Clamp(FMath::CeilToInt(Edge - Settings.ReachBandPx), 0, Band.cols);
		Band.colRange(0, FirstCol).setTo(0);
	}
	else
	{
		const float Edge = Percentile(Xs, 1.f);
		const int32 LastCol = FMath::Clamp(FMath::FloorToInt(Edge + Settings.ReachBandPx), -1, Band.cols - 1);
		Band.colRange(LastCol + 1, Band.cols).setTo(0);
	}
	return CentreOfLargest(Band, DepthMm);
}

TOptional<FPlayerTracker::FAnchorPixel> FPlayerTracker::FindAnchor(const cv::Mat& Player, const cv::Mat& DepthMm, int32 PlayerIndex) const
{
	if (Settings.AnchorMode == ERealSenseAnchorMode::Reach)
	{
		// Player 1 (left) reaches right toward Player 2, and vice versa
		return ReachAnchor(Player, DepthMm, PlayerIndex == 0);
	}
	return NearestAnchor(Player, DepthMm);
}

FPlayerTracker::FResult FPlayerTracker::Process(const cv::Mat& DepthMm)
{
	const cv::Mat Mask = CleanMask(Foreground(DepthMm));

	const int32 Split = FindSplit(Mask);
	SmoothedSplit = SmoothedSplit.IsSet() ? *SmoothedSplit + Settings.SplitSmoothing * (Split - *SmoothedSplit) : float(Split);

	FResult Result;
	Result.Split = FMath::Clamp(FMath::RoundToInt(*SmoothedSplit), 0, Mask.cols);

	// Cut at the divider first, so two players touching hands still split
	cv::Mat Halves[2] = { Mask.clone(), Mask.clone() };
	Halves[0].colRange(Result.Split, Mask.cols).setTo(0);
	Halves[1].colRange(0, Result.Split).setTo(0);

	cv::Mat Occupied = cv::Mat::zeros(Mask.size(), CV_8U);
	for (int32 Index = 0; Index < 2; ++Index)
	{
		const cv::Mat Player = LargestRegion(Halves[Index]);
		if (!Player.empty())
		{
			Result.Anchors[Index] = FindAnchor(Player, DepthMm, Index);
			Occupied |= Player;
		}
	}

	UpdateBackground(DepthMm, Occupied);
	return Result;
}
