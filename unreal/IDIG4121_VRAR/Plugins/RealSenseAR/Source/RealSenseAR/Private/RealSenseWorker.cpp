#include "RealSenseWorker.h"

#include "HAL/RunnableThread.h"
#include "OneEuroFilter.h"
#include "PlayerTracker.h"
#include "RealSenseAR.h"

#if WITH_REALSENSE
THIRD_PARTY_INCLUDES_START
#include <librealsense2/rs.hpp>
#include <librealsense2/rsutil.h>
THIRD_PARTY_INCLUDES_END
#endif

#include "PreOpenCVHeaders.h"
#include <opencv2/core.hpp>
#include "PostOpenCVHeaders.h"

struct FRealSenseWorker::FImpl
{
	explicit FImpl(const FRealSenseSettings& Settings)
		: Tracker(Settings)
	{
		for (FOneEuroFilter& Filter : Smoothers)
		{
			Filter = FOneEuroFilter(Settings.OneEuroMinCutoff, Settings.OneEuroBeta);
		}
	}

#if WITH_REALSENSE
	std::vector<rs2::filter> DepthFilters;
	float DepthUnitMm = 1.f;
	rs2_extrinsics DepthToColor{};
#endif

	FPlayerTracker Tracker;
	TArray<cv::Mat> BackgroundFrames;
	FOneEuroFilter Smoothers[2];
	FRealSenseHandAnchor Last[2];
	TArray<uint8> ColorBack;
};

#if WITH_REALSENSE
namespace
{
	FRealSenseIntrinsics ToIntrinsics(const rs2_intrinsics& I)
	{
		FRealSenseIntrinsics Out;
		Out.Width = I.width;
		Out.Height = I.height;
		Out.Fx = I.fx;
		Out.Fy = I.fy;
		Out.Ppx = I.ppx;
		Out.Ppy = I.ppy;
		return Out;
	}

	void ConfigureDepthSensor(rs2::depth_sensor Sensor)
	{
		// "High Density": Intel's preset for background subtraction
		if (Sensor.supports(RS2_OPTION_VISUAL_PRESET))
		{
			Sensor.set_option(RS2_OPTION_VISUAL_PRESET, RS2_RS400_VISUAL_PRESET_HIGH_DENSITY);
		}
		// The IR projector adds texture, so plain walls get valid depth
		if (Sensor.supports(RS2_OPTION_EMITTER_ENABLED))
		{
			Sensor.set_option(RS2_OPTION_EMITTER_ENABLED, 1.f);
		}
		if (Sensor.supports(RS2_OPTION_LASER_POWER))
		{
			Sensor.set_option(RS2_OPTION_LASER_POWER, Sensor.get_option_range(RS2_OPTION_LASER_POWER).max);
		}
	}

	std::vector<rs2::filter> MakeDepthFilters(const FRealSenseSettings& Settings)
	{
		// Order recommended by the librealsense post-processing docs
		std::vector<rs2::filter> Filters;
		Filters.push_back(rs2::decimation_filter(static_cast<float>(Settings.Decimation)));
		Filters.push_back(rs2::threshold_filter(Settings.NearM, Settings.FarM));

		if (Settings.bSpatialFilter || Settings.bTemporalFilter)
		{
			Filters.push_back(rs2::disparity_transform(true));
			if (Settings.bSpatialFilter)
			{
				Filters.push_back(rs2::spatial_filter());
			}
			if (Settings.bTemporalFilter)
			{
				Filters.push_back(rs2::temporal_filter());
			}
			Filters.push_back(rs2::disparity_transform(false));
		}
		return Filters;
	}
}
#endif // WITH_REALSENSE

FRealSenseWorker::FRealSenseWorker(const FRealSenseSettings& InSettings)
	: Settings(InSettings)
	, Impl(MakeUnique<FImpl>(InSettings))
{
}

FRealSenseWorker::~FRealSenseWorker()
{
	if (Thread)
	{
		// Calls Stop() and waits for Run() to return, which stops the pipeline
		Thread->Kill(true);
		delete Thread;
		Thread = nullptr;
	}
}

void FRealSenseWorker::Start()
{
	check(!Thread);
	Thread = FRunnableThread::Create(this, TEXT("RealSenseWorker"), 0, TPri_AboveNormal);
}

uint32 FRealSenseWorker::Run()
{
#if WITH_REALSENSE
	if (!FRealSenseARModule::IsLibraryLoaded())
	{
		// realsense2.dll is delay-loaded: calling into it now would crash instead of throwing
		SetError(TEXT("realsense2.dll could not be loaded, see the log. Reinstall the Intel RealSense SDK 2.0 and rebuild."));
		return 0;
	}

	try
	{
		rs2::config Config;
		Config.enable_stream(RS2_STREAM_COLOR, Settings.ColorWidth, Settings.ColorHeight, RS2_FORMAT_BGRA8, Settings.Fps);
		Config.enable_stream(RS2_STREAM_DEPTH, Settings.DepthWidth, Settings.DepthHeight, RS2_FORMAT_Z16, Settings.Fps);

		rs2::pipeline Pipeline;
		const rs2::pipeline_profile Profile = Pipeline.start(Config);

		rs2::depth_sensor Sensor = Profile.get_device().first<rs2::depth_sensor>();
		ConfigureDepthSensor(Sensor);
		Impl->DepthUnitMm = Sensor.get_depth_scale() * 1000.f;
		Impl->DepthFilters = MakeDepthFilters(Settings);

		const auto ColorProfile = Profile.get_stream(RS2_STREAM_COLOR).as<rs2::video_stream_profile>();
		const auto DepthProfile = Profile.get_stream(RS2_STREAM_DEPTH).as<rs2::video_stream_profile>();
		// Anchors are tracked in depth space but drawn over the colour image: the two lenses are ~15 mm apart
		Impl->DepthToColor = DepthProfile.get_extrinsics_to(ColorProfile);
		{
			FScopeLock ScopeLock(&Lock);
			ColorIntrinsics = ToIntrinsics(ColorProfile.get_intrinsics());
		}

		UE_LOG(LogRealSense, Log, TEXT("Streaming %s: colour %dx%d, depth %dx%d @ %d fps"),
			UTF8_TO_TCHAR(Profile.get_device().get_info(RS2_CAMERA_INFO_NAME)),
			Settings.ColorWidth, Settings.ColorHeight, Settings.DepthWidth, Settings.DepthHeight, Settings.Fps);
		bStreaming = true;

		while (!bStopRequested)
		{
			rs2::frameset Frames;
			if (!Pipeline.try_wait_for_frames(&Frames, 200))
			{
				continue;
			}

			if (rs2::video_frame Color = Frames.get_color_frame())
			{
				// Copy into the back buffer, then swap: the lock is held for a pointer swap, not a 3.6 MB copy
				const int32 RowBytes = Color.get_width() * 4;
				const int32 Stride = Color.get_stride_in_bytes();
				const uint8* Src = static_cast<const uint8*>(Color.get_data());
				TArray<uint8>& Back = Impl->ColorBack;
				Back.SetNumUninitialized(RowBytes * Color.get_height(), EAllowShrinking::No);
				for (int32 Row = 0; Row < Color.get_height(); ++Row)
				{
					FMemory::Memcpy(Back.GetData() + Row * RowBytes, Src + Row * Stride, RowBytes);
				}

				FScopeLock ScopeLock(&Lock);
				Swap(Back, ColorFront);
				++ColorSeq;
			}

			if (rs2::depth_frame Depth = Frames.get_depth_frame())
			{
				rs2::frame Processed = Depth;
				for (rs2::filter& Filter : Impl->DepthFilters)
				{
					Processed = Filter.process(Processed);
				}
				const rs2::depth_frame Filtered = Processed.as<rs2::depth_frame>();
				// Decimation changed the resolution, so the intrinsics come from the processed frame
				const rs2_intrinsics DepthIntrinsics = Filtered.get_profile().as<rs2::video_stream_profile>().get_intrinsics();

				const cv::Mat Raw(DepthIntrinsics.height, DepthIntrinsics.width, CV_16UC1, const_cast<void*>(Filtered.get_data()));
				cv::Mat DepthMm;
				Raw.convertTo(DepthMm, CV_32F, Impl->DepthUnitMm);
				if (Settings.bMirror)
				{
					// Screen orientation: Player 1 on the left of the image
					cv::flip(DepthMm, DepthMm, 1);
				}

				const double Now = FPlatformTime::Seconds();

				// Background capture: collect frames instead of tracking
				bool bCapturing = false;
				{
					FScopeLock ScopeLock(&Lock);
					bCapturing = BackgroundCaptureAt >= 0.0 && Now >= BackgroundCaptureAt;
				}
				if (bCapturing)
				{
					Impl->BackgroundFrames.Add(DepthMm.clone());
					if (Impl->BackgroundFrames.Num() >= Settings.BackgroundFrames)
					{
						Impl->Tracker.CaptureBackground(Impl->BackgroundFrames, DepthIntrinsics.fx * Settings.Decimation);
						Impl->BackgroundFrames.Reset();
						FScopeLock ScopeLock(&Lock);
						BackgroundCaptureAt = -1.0;
						UE_LOG(LogRealSense, Log, TEXT("Background captured"));
					}
					continue;
				}

				const FPlayerTracker::FResult Result = Impl->Tracker.Process(DepthMm);

				FRealSenseHandAnchor Fresh[2];
				for (int32 Index = 0; Index < 2; ++Index)
				{
					FRealSenseHandAnchor& Anchor = Fresh[Index];
					if (Result.Anchors[Index].IsSet())
					{
						const FPlayerTracker::FAnchorPixel& Pixel = *Result.Anchors[Index];

						// Back to the sensor's own orientation: deprojection and extrinsics are defined there.
						// Mirroring is a display concern, applied once in RealSenseMath::CameraToUnrealLocal.
						const float SensorPixel[2] = {
							Settings.bMirror ? DepthIntrinsics.width - 1 - Pixel.U : Pixel.U,
							Pixel.V
						};
						float DepthPoint[3];
						rs2_deproject_pixel_to_point(DepthPoint, &DepthIntrinsics, SensorPixel, Pixel.DepthMm / 1000.f);
						float ColorPoint[3];
						rs2_transform_point_to_point(ColorPoint, &Impl->DepthToColor, DepthPoint);

						const FVector Point(ColorPoint[0], ColorPoint[1], ColorPoint[2]);
						Anchor.bValid = true;
						Anchor.CameraPoint = Impl->Smoothers[Index].Filter(Point, Now);
						Anchor.DepthPixel = FVector2D(Pixel.U, Pixel.V);
						Anchor.Timestamp = Now;
						Impl->Last[Index] = Anchor;
					}
					else if (Impl->Last[Index].bValid && Now - Impl->Last[Index].Timestamp <= Settings.AnchorHoldS)
					{
						// Missed for a moment: keep the last anchor briefly
						Anchor = Impl->Last[Index];
						Anchor.bStale = true;
					}
					else
					{
						Impl->Smoothers[Index].Reset();
						Impl->Last[Index] = FRealSenseHandAnchor();
					}
				}

				FScopeLock ScopeLock(&Lock);
				Anchors[0] = Fresh[0];
				Anchors[1] = Fresh[1];
			}
		}

		Pipeline.stop();
	}
	catch (const rs2::error& E)
	{
		SetError(FString::Printf(TEXT("%hs(%hs): %hs"), E.get_failed_function().c_str(), E.get_failed_args().c_str(), E.what()));
	}
	catch (const std::exception& E)
	{
		SetError(UTF8_TO_TCHAR(E.what()));
	}
#else
	SetError(TEXT("built without librealsense2. Install the Intel RealSense SDK 2.0 (Windows) or 'brew install librealsense' (Mac), then rebuild."));
#endif

	bStreaming = false;
	return 0;
}

bool FRealSenseWorker::TakeColorFrame(TArray<uint8>& OutBGRA, uint64& InOutSeq)
{
	FScopeLock ScopeLock(&Lock);
	if (ColorSeq == InOutSeq || ColorFront.IsEmpty())
	{
		return false;
	}
	// The caller's (usually empty) array becomes the next front buffer
	Swap(OutBGRA, ColorFront);
	InOutSeq = ColorSeq;
	return true;
}

void FRealSenseWorker::GetAnchors(FRealSenseHandAnchor (&OutAnchors)[2]) const
{
	FScopeLock ScopeLock(&Lock);
	OutAnchors[0] = Anchors[0];
	OutAnchors[1] = Anchors[1];
}

FRealSenseIntrinsics FRealSenseWorker::GetColorIntrinsics() const
{
	FScopeLock ScopeLock(&Lock);
	return ColorIntrinsics;
}

void FRealSenseWorker::RequestBackground(double DelaySeconds)
{
	FScopeLock ScopeLock(&Lock);
	BackgroundCaptureAt = FPlatformTime::Seconds() + DelaySeconds;
}

double FRealSenseWorker::GetBackgroundCountdown() const
{
	FScopeLock ScopeLock(&Lock);
	return BackgroundCaptureAt < 0.0 ? -1.0 : FMath::Max(0.0, BackgroundCaptureAt - FPlatformTime::Seconds());
}

FString FRealSenseWorker::GetError() const
{
	FScopeLock ScopeLock(&Lock);
	return Error;
}

void FRealSenseWorker::SetError(const FString& Message)
{
	UE_LOG(LogRealSense, Error, TEXT("RealSense stopped: %s"), *Message);
	FScopeLock ScopeLock(&Lock);
	Error = Message;
}
