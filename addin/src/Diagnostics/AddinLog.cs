using System.Text;

namespace RevitMCP.Addin.Diagnostics;

/// <summary>
/// Minimal thread-safe file logger (NFR-5). Writes to
/// %LOCALAPPDATA%\RevitMCP\logs\addin-yyyyMMdd.log. The auth token is never
/// passed here; callers must redact before logging.
/// </summary>
public static class AddinLog
{
    private static readonly object Gate = new();
    private static string? _logDir;

    public static void Init()
    {
        var baseDir = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        _logDir = Path.Combine(baseDir, "RevitMCP", "logs");
        Directory.CreateDirectory(_logDir);
        Info("AddinLog initialised.");
    }

    public static void Info(string message) => Write("INFO", message);
    public static void Warn(string message) => Write("WARN", message);
    public static void Error(string message) => Write("ERROR", message);

    public static void Error(string message, Exception ex) =>
        Write("ERROR", $"{message} :: {ex.GetType().Name}: {ex.Message}\n{ex.StackTrace}");

    /// <summary>Structured per-request line for correlation (NFR-5).</summary>
    public static void Request(string? id, string? method, long durationMs, string outcome) =>
        Write("REQ", $"id={id} method={method} duration_ms={durationMs} outcome={outcome}");

    private static void Write(string level, string message)
    {
        try
        {
            if (_logDir == null) return;
            var file = Path.Combine(_logDir, $"addin-{DateTime.Now:yyyyMMdd}.log");
            var line = $"{DateTime.Now:HH:mm:ss.fff} [{level}] {message}{Environment.NewLine}";
            lock (Gate)
            {
                File.AppendAllText(file, line, Encoding.UTF8);
            }
        }
        catch
        {
            // Logging must never throw into Revit.
        }
    }
}
