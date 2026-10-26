using System;
using System.IO;
using Microsoft.Extensions.Logging;
using UnrealBuildTool;

// Prebuilt librealsense2, looked up in this order:
//   1. $REALSENSE_SDK_DIR            (include/ and lib/ beneath it)
//   2. a copy vendored next to this file: include/, lib/<Platform>/
//   3. the platform's usual install: Homebrew on Mac, Intel's installer on Windows, /usr on Linux
//
// Never fails the build: without the SDK the module compiles with WITH_REALSENSE=0, the project still
// opens and plays, and the camera reports on screen why it is off. Set REALSENSE_DISABLE=1 to force that.
public class LibRealSense : ModuleRules
{
	public LibRealSense(ReadOnlyTargetRules Target) : base(Target)
	{
		Type = ModuleType.External;

		if (!TrySetup(Target))
		{
			PublicDefinitions.Add("WITH_REALSENSE=0");
		}
	}

	private bool TrySetup(ReadOnlyTargetRules Target)
	{
		if (Environment.GetEnvironmentVariable("REALSENSE_DISABLE") == "1")
		{
			Logger.LogWarning("REALSENSE_DISABLE=1: building RealSenseAR without camera support.");
			return false;
		}

		string Platform = Target.Platform.ToString();
		string Root = FindSdkRoot(Target);
		if (Root == null)
		{
			Logger.LogWarning(
				"librealsense2 not found, building RealSenseAR without camera support. Install it " +
				"(Windows: Intel RealSense SDK 2.0, Mac: 'brew install librealsense') or set REALSENSE_SDK_DIR, then rebuild.");
			return false;
		}

		bool bVendored = Root.StartsWith(ModuleDirectory);

		if (Target.Platform == UnrealTargetPlatform.Win64)
		{
			string Lib = FirstExisting(
				Path.Combine(Root, "lib", Platform, "realsense2.lib"),
				Path.Combine(Root, "lib", "x64", "realsense2.lib"));
			string Dll = FirstExisting(
				Path.Combine(Root, "lib", Platform, "realsense2.dll"),
				Path.Combine(Root, "bin", "x64", "realsense2.dll"));
			if (Lib == null || Dll == null)
			{
				Logger.LogWarning("librealsense2 headers found in {Root} but realsense2.lib/.dll missing: building without camera support.", Root);
				return false;
			}

			PublicAdditionalLibraries.Add(Lib);
			PublicDelayLoadDLLs.Add("realsense2.dll");
			// Copied next to the plugin binary; the module loads it from there on startup
			RuntimeDependencies.Add("$(BinaryOutputDir)/realsense2.dll", Dll);
		}
		else if (Target.Platform == UnrealTargetPlatform.Mac)
		{
			string Dylib = FirstExisting(
				Path.Combine(Root, "lib", Platform, "librealsense2.dylib"),
				Path.Combine(Root, "lib", "librealsense2.dylib"));
			if (Dylib == null)
			{
				Logger.LogWarning("librealsense2 headers found in {Root} but librealsense2.dylib missing: building without camera support.", Root);
				return false;
			}

			PublicAdditionalLibraries.Add(Dylib);
			// A Homebrew dylib loads from its absolute install name, which is fine for the editor.
			// Packaged builds need a vendored copy (with @rpath install names) to stage it.
			if (bVendored)
			{
				RuntimeDependencies.Add(Dylib);
			}
		}
		else if (Target.Platform == UnrealTargetPlatform.Linux)
		{
			string So = FirstExisting(
				Path.Combine(Root, "lib", Platform, "librealsense2.so"),
				Path.Combine(Root, "lib", "librealsense2.so"),
				Path.Combine(Root, "lib", "x86_64-linux-gnu", "librealsense2.so"));
			if (So == null)
			{
				Logger.LogWarning("librealsense2 headers found in {Root} but librealsense2.so missing: building without camera support.", Root);
				return false;
			}

			PublicAdditionalLibraries.Add(So);
			if (bVendored)
			{
				RuntimeDependencies.Add(So);
			}
		}
		else
		{
			return false;
		}

		PublicSystemIncludePaths.Add(Path.Combine(Root, "include"));
		PublicDefinitions.Add("WITH_REALSENSE=1");
		return true;
	}

	private string FindSdkRoot(ReadOnlyTargetRules Target)
	{
		string FromEnv = Environment.GetEnvironmentVariable("REALSENSE_SDK_DIR");
		if (!string.IsNullOrEmpty(FromEnv) && HasHeaders(FromEnv))
		{
			return FromEnv;
		}

		if (HasHeaders(ModuleDirectory))
		{
			return ModuleDirectory;
		}

		string[] Defaults;
		if (Target.Platform == UnrealTargetPlatform.Win64)
		{
			Defaults = new[] { @"C:\Program Files (x86)\Intel RealSense SDK 2.0", @"C:\Program Files\Intel RealSense SDK 2.0" };
		}
		else if (Target.Platform == UnrealTargetPlatform.Mac)
		{
			Defaults = new[] { "/opt/homebrew/opt/librealsense", "/usr/local/opt/librealsense" };
		}
		else
		{
			Defaults = new[] { "/usr/local", "/usr" };
		}

		foreach (string Candidate in Defaults)
		{
			if (HasHeaders(Candidate))
			{
				return Candidate;
			}
		}
		return null;
	}

	private static bool HasHeaders(string Root)
	{
		return File.Exists(Path.Combine(Root, "include", "librealsense2", "rs.hpp"));
	}

	private static string FirstExisting(params string[] Paths)
	{
		foreach (string Candidate in Paths)
		{
			if (File.Exists(Candidate))
			{
				return Candidate;
			}
		}
		return null;
	}
}
