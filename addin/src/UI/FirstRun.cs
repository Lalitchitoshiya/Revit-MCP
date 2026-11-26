using RevitMCP.Addin.Diagnostics;

namespace RevitMCP.Addin.UI;

/// <summary>
/// First-run / upgrade bookkeeping. Creates the data folders and records which
/// version last ran (%LOCALAPPDATA%\RevitMCP\installed-version.txt) so support
/// logs show upgrades. Deliberately shows no dialog at Revit startup. On the
/// first run of a version RevitMcpApp registers the MCP server with Claude in
/// the background (covers installers other than our MSI); the ribbon's
/// "Connect Claude" button repeats that on demand.
/// </summary>
public static class FirstRun
{
    public static bool IsFirstRunOfThisVersion { get; private set; }

    public static void Record()
    {
        try
        {
            Directory.CreateDirectory(Product.DataDirectory);
            Directory.CreateDirectory(Product.LogDirectory);
            var stamp = Path.Combine(Product.DataDirectory, "installed-version.txt");
            var previous = File.Exists(stamp) ? File.ReadAllText(stamp).Trim() : null;
            if (previous == Product.Version) return;

            IsFirstRunOfThisVersion = true;
            AddinLog.Info(previous == null
                ? $"First run of {Product.Name} {Product.Version}."
                : $"Upgraded {Product.Name} {previous} -> {Product.Version}.");
            File.WriteAllText(stamp, Product.Version);
        }
        catch (Exception ex)
        {
            AddinLog.Warn($"First-run bookkeeping failed: {ex.Message}");
        }
    }
}
