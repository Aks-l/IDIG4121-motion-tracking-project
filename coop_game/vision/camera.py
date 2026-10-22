"""Intel RealSense D435: depth stream, sensor preset and post-processing."""

import numpy as np
import pyrealsense2 as rs

from .. import config
from .geometry import Intrinsics


class DepthCamera:
    def __init__(self):
        self.pipeline = rs.pipeline()
        rs_config = rs.config()

        width, height = config.DEPTH_SIZE
        rs_config.enable_stream(
            rs.stream.depth, width, height, rs.format.z16, config.DEPTH_FPS
        )
        profile = self.pipeline.start(rs_config)

        sensor = profile.get_device().first_depth_sensor()
        self._configure(sensor)
        self.depth_mm_per_unit = sensor.get_depth_scale() * 1000.0

        self.filters = self._make_filters()
        # Known after the first frame: decimation changes the resolution
        self.intrinsics = None

    @staticmethod
    def _configure(sensor):
        # "High Density": Intel's preset for background subtraction
        if sensor.supports(rs.option.visual_preset):
            sensor.set_option(
                rs.option.visual_preset,
                int(rs.rs400_visual_preset.high_density),
            )

        # The IR projector adds texture, so plain walls get valid depth
        if sensor.supports(rs.option.emitter_enabled):
            sensor.set_option(rs.option.emitter_enabled, 1)

        if sensor.supports(rs.option.laser_power):
            laser = sensor.get_option_range(rs.option.laser_power)
            sensor.set_option(rs.option.laser_power, laser.max)

    @staticmethod
    def _make_filters():
        # Order recommended by the librealsense post-processing docs
        decimation = rs.decimation_filter()
        decimation.set_option(rs.option.filter_magnitude, config.DECIMATION)

        threshold = rs.threshold_filter()
        threshold.set_option(rs.option.min_distance, config.NEAR_M)
        threshold.set_option(rs.option.max_distance, config.FAR_M)

        filters = [decimation, threshold]

        if config.USE_SPATIAL_FILTER or config.USE_TEMPORAL_FILTER:
            filters.append(rs.disparity_transform(True))
            if config.USE_SPATIAL_FILTER:
                filters.append(rs.spatial_filter())
            if config.USE_TEMPORAL_FILTER:
                filters.append(rs.temporal_filter())
            filters.append(rs.disparity_transform(False))

        return filters

    def read(self):
        """Next depth image in mm (float32, 0 = no data) and its intrinsics."""
        frame = self.pipeline.wait_for_frames().get_depth_frame()
        if not frame:
            return None, None

        for depth_filter in self.filters:
            frame = depth_filter.process(frame)
        frame = frame.as_depth_frame()

        if self.intrinsics is None:
            i = frame.profile.as_video_stream_profile().get_intrinsics()
            self.intrinsics = Intrinsics(
                i.width, i.height, i.fx, i.fy, i.ppx, i.ppy
            )

        depth = (
            np.asanyarray(frame.get_data()).astype(np.float32)
            * self.depth_mm_per_unit
        )
        return depth, self.intrinsics

    def stop(self):
        self.pipeline.stop()
