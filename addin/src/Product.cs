using System.Reflection;

namespace RevitMCP.Addin;

/// <summary>
/// Product identity and well-known paths, shared by the ribbon, health.check and
/// the logs. Installed layout (Autodesk .bundle, see installer/):
///
///   RevitMCP.bundle\Contents\&lt;year&gt;\RevitMCP.Addin.dll   (this assembly)
///   RevitMCP.bundle\Contents\Server\revit-mcp-server.exe
///   RevitMCP.bundle\Contents\Resources\help.html
///
/// In a developer deploy (addin\deploy.ps1) the Server/Resources folders do not
/// exist; callers must handle that.
/// </summary>
public static class Product
{
    public const string Name = "Revit MCP";

    /// <summary>Semantic version from the build (-p:Version), without the +commit suffix.</summary>
    public static string Version { get; } = ReadVersion();

    public static string AddinDirectory { get; } =
        Path.GetDirectoryName(typeof(Product).Assembly.Location) ?? AppContext.BaseDirectory;

    /// <summary>The .bundle\Contents folder when installed; null in a developer deploy.</summary>
    public static string? ContentsDirectory
    {
        get
        {
            var parent = Directory.GetParent(AddinDirectory)?.FullName;
            return parent != null && Directory.Exists(Path.Combine(parent, "Server")) ? parent : null;
        }
    }

    public static string? ServerExe
    {
        get
        {
            var c = ContentsDirectory;
            var exe = c == null ? null : Path.Combine(c, "Server", "revit-mcp-server.exe");
            return exe != null && File.Exists(exe) ? exe : null;
        }
    }

    public static string? HelpFile
    {
        get
        {
            var c = ContentsDirectory;
            var f = c == null ? null : Path.Combine(c, "Resources", "help.html");
            return f != null && File.Exists(f) ? f : null;
        }
    }

    /// <summary>%LOCALAPPDATA%\RevitMCP (session, logs, audit, auth).</summary>
    public static string DataDirectory { get; } = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "RevitMCP");

    public static string LogDirectory => Path.Combine(DataDirectory, "logs");

    private static string ReadVersion()
    {
        var info = typeof(Product).Assembly
            .GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion;
        if (string.IsNullOrEmpty(info))
            return typeof(Product).Assembly.GetName().Version?.ToString() ?? "0.0.0";
        var plus = info.IndexOf('+');
        return plus >= 0 ? info[..plus] : info;
    }
}
