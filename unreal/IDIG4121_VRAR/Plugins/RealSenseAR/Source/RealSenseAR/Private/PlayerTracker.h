#pragma once

#include "CoreMinimal.h"
#include "RealSenseTypes.h"

#include "PreOpenCVHeaders.h"
#include <opencv2/core.hpp>
#include "PostOpenCVHeaders.h"

/**
 * Depth image in (mm, float, screen orientation), Player 1 / Player 2 anchor pixels out.
 * A straight port of coop_game/vision (background.py + players.py): background subtraction against
 * a learned per-pixel depth of the empty room, an adaptive divider between the players, and each
 * player's hand found as the point reaching farthest toward the other.
 *
 * Pure image work: no librealsense, no UObjects, runs on the worker thread only.
 */
class FPlayerTracker
{
public:
	struct FAnchorPixel
	{
		float U = 0.f;
		float V = 0.f;
		float DepthMm = 0.f;
	};

	struct FResult
	{
		/** [0] = Player 1 (left on screen), [1] = Player 2. */
		TOptional<FAnchorPixel> Anchors[2];
		int32 Split = 0;
	};

	explicit FPlayerTracker(const FRealSenseSettings& InSettings);

	/** Median of the empty room. FxFull = depth focal length at full (undecimated) resolution. */
	void CaptureBackground(const TArray<cv::Mat>& Frames, float FxFull);
	bool HasBackground() const { return !BgDepth.empty(); }

	FResult Process(const cv::Mat& DepthMm);

private:
	cv::Mat Foreground(const cv::Mat& DepthMm) const;
	void UpdateBackground(const cv::Mat& DepthMm, const cv::Mat& Occupied);

	int32 FindSplit(const cv::Mat& Mask) const;
	cv::Mat LargestRegion(const cv::Mat& Mask) const;
	cv::Mat UpperBody(const cv::Mat& Player) const;

	TOptional<FAnchorPixel> FindAnchor(const cv::Mat& Player, const cv::Mat& DepthMm, int32 PlayerIndex) const;
	TOptional<FAnchorPixel> NearestAnchor(const cv::Mat& Player, const cv::Mat& DepthMm) const;
	TOptional<FAnchorPixel> ReachAnchor(const cv::Mat& Player, const cv::Mat& DepthMm, bool bTowardRight) const;
	static TOptional<FAnchorPixel> CentreOfLargest(const cv::Mat& Candidates, const cv::Mat& DepthMm);

	FRealSenseSettings Settings;

	cv::Mat BgDepth;   // CV_32F mm per pixel, 0 = never saw anything there
	cv::Mat BgMargin;  // CV_32F mm a pixel must be in front of it
	TOptional<float> SmoothedSplit;
};
