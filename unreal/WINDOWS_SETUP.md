# Running the Unreal project on Windows

The project is `unreal/IDIG4121_VRAR/IDIG4121_VRAR.uproject` on the `3d` branch. It contains C++ code (the game module and the `RealSenseAR` plugin), so Windows has to compile it once with Visual Studio before the editor can open it. "The project doesn't start" almost always means that compile failed, or never ran.

## 1. Install

| What | Notes |
|---|---|
| **Unreal Engine 5.8** | From the Epic Games Launcher. It must be 5.8: the project targets it (`EngineAssociation: 5.8`). |
| **Visual Studio 2022** (Community is fine) | In the installer, tick the workloads **Game development with C++** and **Desktop development with C++**. Under *Individual components* make sure these are ticked: **MSVC v143 build tools (latest)** and a **Windows 11 SDK** (or Windows 10 SDK 10.0.22621 or newer). If Epic's 5.8 release notes ask for a newer Visual Studio, use that instead. |
| **Intel RealSense SDK 2.0** | `Intel.RealSense.SDK-WIN10-<version>.exe` from github.com/IntelRealSense/librealsense/releases. Keep the default install folder, `C:\Program Files (x86)\Intel RealSense SDK 2.0`, because the build looks there. It also installs **RealSense Viewer**, which is handy for testing the camera. If you skip the SDK, the project still builds and opens, but the camera stays off and says why on screen. |
| **Git** | To clone the repo. |

## 2. Get the project

Clone to a **short path**. Unreal's build folders nest deeply, and Windows' 260-character path limit breaks builds under long paths such as `C:\Users\<name>\Documents\GitHub\...`.

```bat
cd C:\
mkdir dev
cd dev
git clone -b 3d https://github.com/Aks-l/IDIG4121-motion-tracking-project.git
```

If you copied the project from the Mac instead, delete any `Binaries`, `Intermediate`, `Saved` and `DerivedDataCache` folders in `IDIG4121_VRAR` and in `IDIG4121_VRAR\Plugins\RealSenseAR`. Mac binaries can't run on Windows.

## 3. Build

1. In `C:\dev\IDIG4121-motion-tracking-project\unreal\IDIG4121_VRAR`, right-click `IDIG4121_VRAR.uproject` and choose **Generate Visual Studio project files**.
   - If that menu entry is missing, choose **Switch Unreal Engine version…**, pick 5.8, then try again.
2. Open the generated `IDIG4121_VRAR.sln`. If Visual Studio offers to install missing components, accept.
3. Set the toolbar to **Development Editor** and **Win64**. Right-click the `IDIG4121_VRAR` project and choose **Build**. Wait for `Build succeeded`.
4. Double-click `IDIG4121_VRAR.uproject`. It opens `Lvl_CoopAR`.

Command-line alternative to steps 2–3:

```bat
"C:\Program Files\Epic Games\UE_5.8\Engine\Build\BatchFiles\Build.bat" IDIG4121_VRAREditor Win64 Development -Project="C:\dev\IDIG4121-motion-tracking-project\unreal\IDIG4121_VRAR\IDIG4121_VRAR.uproject" -WaitMutex
```

## 4. Test

1. Plug the D435 into a **USB 3** port (often blue or marked SS). Open RealSense Viewer and check that colour and depth both stream, then close the Viewer: only one program can use the camera at a time.
2. In Unreal, press **Play**. The Output Log should show `Streaming Intel RealSense D435…` and `Mirror camera: HFOV …`.
3. Step out of view during the 3-second countdown while the empty room is captured. Press **B** to recapture it. Click into the viewport first so it gets the key.
4. With **Draw Anchors** on, the blue and green spheres should sit on the players' hands.

## If it still fails

| Symptom | Fix |
|---|---|
| "Modules are missing or built with a different engine version… could not be compiled" | The compile failed. Build from Visual Studio (step 3) to see the real error. Also check the log at `%LOCALAPPDATA%\UnrealBuildTool\Log.txt`. |
| No "Generate Visual Studio project files" entry | UE 5.8 isn't installed or registered: install it, or use *Switch Unreal Engine version*. |
| `MSVC toolchain not found` / `No Windows SDK` | Add those components in the Visual Studio Installer (section 1). |
| Errors mentioning paths over 260 characters | Clone to `C:\dev` (section 2), or enable Windows long paths. |
| Red `RealSense: … No device connected` in game | Camera unplugged, on USB 2, or in use by RealSense Viewer. |
| Red `RealSense: built without librealsense2…` | The SDK wasn't found at build time. Install it at the default path (or set `REALSENSE_SDK_DIR`), delete `Plugins\RealSenseAR\Intermediate`, and rebuild. |
| Red `realsense2.dll could not be loaded` | Reinstall the SDK and rebuild. The build copies `realsense2.dll` into `Plugins\RealSenseAR\Binaries\Win64`. |

---

## Prompt for Claude Code on the Windows computer

Open Claude Code in `C:\dev\IDIG4121-motion-tracking-project` and paste:

```text
I need to get the Unreal Engine 5.8 project in unreal/IDIG4121_VRAR (branch 3d) building and running on this Windows PC. It was developed on a Mac and has only ever been compiled with clang, so this is its first MSVC build.

Context:
- C++ game module "IDIG4121_VRAR" (Source/) plus a project plugin "RealSenseAR" (Plugins/RealSenseAR) that uses librealsense2 (Intel RealSense SDK 2.0) and the engine's OpenCV plugin. unreal/WINDOWS_SETUP.md describes the setup; Plugins/RealSenseAR/README.md describes the architecture.
- LibRealSense.Build.cs looks for the SDK in REALSENSE_SDK_DIR, then "C:\Program Files (x86)\Intel RealSense SDK 2.0". If it isn't found, the plugin builds with WITH_REALSENSE=0 (camera disabled) instead of failing.

Please:
1. Check the prerequisites and tell me exactly what is missing, with how to install it:
   - UE 5.8 installed (look for C:\Program Files\Epic Games\UE_5.8)
   - Visual Studio with the MSVC v143 toolset and a Windows SDK (use "C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe" -products * -format json)
   - the Intel RealSense SDK 2.0 at the path above
   - whether the repo path is short enough to stay under Windows' 260-character limit
2. Make sure we're on the latest 3d branch (git pull). Delete any Binaries/, Intermediate/, Saved/ and DerivedDataCache/ folders left from the Mac, both in unreal/IDIG4121_VRAR and in its Plugins/RealSenseAR.
3. Build from the command line and capture the output:
   "C:\Program Files\Epic Games\UE_5.8\Engine\Build\BatchFiles\Build.bat" IDIG4121_VRAREditor Win64 Development -Project="<full path>\unreal\IDIG4121_VRAR\IDIG4121_VRAR.uproject" -WaitMutex
4. If it fails, read the first real errors (also %LOCALAPPDATA%\UnrealBuildTool\Log.txt) and fix them. MSVC is stricter than clang about things like shadowed variables (C4456/C4458 are errors in Unreal), implicit conversions and missing includes. Keep every fix portable, so it still compiles on the Mac with clang. Don't remove features or disable the camera to make it build. Rebuild until it succeeds.
5. Confirm that realsense2.dll was copied into Plugins/RealSenseAR/Binaries/Win64. Tell me whether the log said "building RealSenseAR without camera support".
6. Launch the editor with the project, and tell me what to check by hand (WINDOWS_SETUP.md, section 4).
Before committing or pushing anything, show me the diff and ask me first.
```
