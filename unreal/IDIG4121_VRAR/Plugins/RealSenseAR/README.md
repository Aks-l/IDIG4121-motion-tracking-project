# RealSense AR

The Unreal Engine 5.8 C++ port of `coop_game/vision`, plus the AR mirror display. The plugin handles the camera, tracking, the video feed and projection. The gameplay (couch, obstacles) lives in the game module under `Source/IDIG4121_VRAR/CoopAR/`.

```
FRealSenseWorker (FRunnable, own thread, 30 fps)
  rs2::pipeline  colour BGRA8 1280x720 + depth Z16 848x480, synced framesets
   ├─ colour → back buffer ⇄ front buffer (swap under lock)
   └─ depth  → decimate ×2, threshold 0.5–4.5 m, spatial → mm (cv::Mat) → mirror
             → FPlayerTracker (background subtraction, split, reach anchor; OpenCV 4.5.5 from UE)
             → rs2_deproject_pixel_to_point → rs2_transform_point_to_point(depth→colour)
             → 1€ filter → anchors (metres, colour camera frame)
URealSenseSubsystem (GameInstance, ticks on game thread, 60+ fps)
   ├─ TakeColorFrame → ENQUEUE_RENDER_COMMAND → RHICmdList.UpdateTexture2D → UTexture2D "RealSenseColor"
   └─ caches both anchors once per frame
ARealSenseMirrorCamera (virtual twin of the D435 colour lens)
   ├─ FOV = 2·atan(W / 2fx), aspect = W/H (constrained), off-centre projection = principal point
   ├─ post-process material: video wherever no geometry was drawn
   └─ CameraToWorld(p) = CameraTransform · (100·(z, ±x, −y))
ACarriedObject / AZObstacle / AObstacleSpawner (game module)
```

## Setup

1. **SDK**: `brew install librealsense` (Mac) or Intel RealSense SDK 2.0 (Windows). For packaged builds, copy `include/` and `lib/<Platform>/` into `Source/ThirdParty/LibRealSense/`, or set `REALSENSE_SDK_DIR`. If no SDK is found, the plugin still builds with `WITH_REALSENSE=0`: the project opens and plays, and the camera explains on screen why it is off. Set `REALSENSE_DISABLE=1` to force that mode. For Windows (Visual Studio, first build), see `unreal/WINDOWS_SETUP.md` in the repo.
2. **macOS caveat**: on recent macOS versions, librealsense often needs root to claim the camera's USB interface ("failed to claim interface"). If the log shows that, launch the editor with `sudo`, or run the installation on Windows, where the SDK is fully supported.
3. **USB 3**: colour 1280x720 plus depth 848x480 at 30 fps needs a USB 3 port and cable.
4. Settings live under Project Settings > Plugins > RealSense AR. They are the same numbers as `config.py`.

## AR background material (`M_ARBackground`)

Create a Material with:

- Material Domain: **Post Process**. Blendable Location: **Scene Color After Tonemapping**.
- `ScreenPosition` (ViewportUV) → split into U and V. Make a scalar parameter **Mirror** (default 1), compute `U' = lerp(U, 1-U, Mirror)`, then `Append(U', V)`.
- `TextureSampleParameter2D` **Video**, Sampler Type **Linear Color**, UVs set to the result above.
- `SceneTexture:SceneDepth` (R) > 50000 → mask, meaning nothing virtual was drawn on this pixel.
- `Lerp(SceneTexture:PostProcessInput0, Video, mask)` → Emissive Color.

Assign it to the mirror camera's **Background Material**.

The video texture is created with SRGB off on purpose. After the tonemapper, values are already display-encoded, so the camera's bytes pass through unchanged and the mirror looks like the raw camera image. Virtual objects still get the full lighting and tonemapping.

## Level

`/Game/CoopAR/Lvl_CoopAR` is already set up this way, with `M_ARBackground`, `BP_CoopARGameMode` (no pawn), `BP_Couch` and `BP_Obstacle`. Both Blueprints use cubes as stand-in meshes. The couch's size lives in the placed actor's scale (0.8, 1.6, 0.6), because its mesh is the root component.

- Use an empty level: no sky sphere, sky atmosphere or fog, because the "empty" pixels are where the video shows through. A directional light plus a sky light is enough to light the couch.
- Place one `ARealSenseMirrorCamera`, set **Camera Height M** and **Camera Pitch Deg** to the real camera's values, and tick **Draw Anchors** for the alignment check. Set **Auto Activate For Player = Player 0**, or use a GameMode with no default pawn.
- Make a Blueprint of `ACarriedObject` with the couch mesh. Model the mesh with its length along local +Y and its seat facing +Z.
- Place an `AObstacleSpawner` and give it a Blueprint of `AZObstacle` with a mesh.
- Background capture runs by itself. As soon as the camera streams there's a 3 s countdown, shown on screen, then the empty room is learned, so everyone must be out of view. Press **B** (`RecaptureBackgroundKey` on the mirror camera) to learn it again, e.g. after moving the camera or furniture. The switch and the countdown length are in Project Settings > Plugins > RealSense AR (`bAutoCaptureBackground`, `BackgroundCaptureDelayS`). Camera errors appear on screen in red.
- `Lvl_CoopAR` is the editor startup map and the game default map.

## Alignment check

With **Draw Anchors** on, the spheres should sit on the hands in the video at any distance from the camera.

- **Constant sideways offset**: check the mirror flag and the sign of the off-centre projection.
- **Offset that grows toward the edges**: the FOV is wrong. Check that the colour intrinsics were logged ("Mirror camera: HFOV …").
- **Offset that grows with height**: Camera Height or Camera Pitch don't match the real camera. This only affects floor-relative gameplay, not the overlay itself.
