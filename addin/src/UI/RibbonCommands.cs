using System.Diagnostics;
using System.Text;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using RevitMCP.Addin.Audit;
using RevitMCP.Addin.Auth;
using RevitMCP.Addin.Diagnostics;

namespace RevitMCP.Addin.UI;

/// <summary>Status: is Claude able to reach this Revit, and with what access.</summary>
[Transaction(TransactionMode.ReadOnly)]
public sealed class StatusCommand : IExternalCommand
{
    public Result Execute(ExternalCommandData commandData, ref string message, ElementSet elements)
    {
        var app = RevitMcpApp.Current;
        var server = app?.Server;
        var headline = app == null ? "Revit MCP is not running. See the logs."
            : server == null ? "Paused: Claude cannot reach this Revit session."
            : server.ClientConnected ? "Working: Claude is using this Revit session right now."
            : server.LastRequestAt != null ? "Ready: Claude has used this Revit session."
            : "Ready. Claude hasn't asked anything yet.";

        var details = Details(app, server);
        var td = new TaskDialog(Product.Name)
        {
            MainInstruction = headline,
            MainContent = details,
            CommonButtons = TaskDialogCommonButtons.Close,
        };
        td.AddCommandLink(TaskDialogCommandLinkId.CommandLink1, "Copy details", "For a support request.");
        td.AddCommandLink(TaskDialogCommandLinkId.CommandLink2, "Open logs folder");

        var choice = td.Show();
        if (choice == TaskDialogResult.CommandLink1)
            Shell.CopyToClipboard($"{Product.Name} status\n{headline}\n{details}\nOS: {Environment.OSVersion}");
        else if (choice == TaskDialogResult.CommandLink2)
            Shell.OpenFolder(Product.LogDirectory);
        return Result.Succeeded;
    }

    private static string Details(RevitMcpApp? app, Server.SocketServer? server)
    {
        var sb = new StringBuilder();
        sb.AppendLine($"Version: {Product.Version} (Revit {app?.RevitVersion})");
        sb.AppendLine(server != null ? $"Listening: 127.0.0.1:{server.Port} (this PC only)" : "Listening: no");
        // Claude opens a connection per request, so idle between requests is normal.
        sb.AppendLine(server?.LastRequestAt is DateTime last
            ? $"Last request: {last:HH:mm:ss} ({server.LastClientIdentity})"
            : "Last request: none yet. In Claude, ask \"Check the Revit connection\".");
        sb.AppendLine($"Requests handled: {server?.RequestsServed ?? 0}");
        sb.AppendLine(File.Exists(TokenValidator.DefaultPolicyPath)
            ? "Access control: scoped tokens enabled (auth.json)"
            : "Access control: default (full access for the local Claude client)");
        sb.AppendLine($"Audit log: {AuditLog.Path}");
        sb.AppendLine($"Logs: {Product.LogDirectory}");
        sb.Append(Product.ServerExe != null ? $"MCP server: {Product.ServerExe}" : "MCP server: not bundled (developer deploy)");
        return sb.ToString();
    }
}

/// <summary>Register the bundled MCP server with Claude Desktop / Claude Code.</summary>
[Transaction(TransactionMode.ReadOnly)]
public sealed class ConnectClaudeCommand : IExternalCommand
{
    public Result Execute(ExternalCommandData commandData, ref string message, ElementSet elements)
    {
        var exe = Product.ServerExe;
        if (exe == null)
        {
            TaskDialog.Show(Product.Name,
                "This is a developer deploy: the MCP server is not bundled with the add-in.\n\n" +
                "Register the server from the repo's .mcp.json (see .mcp.json.example), or install the Revit MCP MSI.");
            return Result.Succeeded;
        }

        var (code, output) = Shell.Run(exe, "setup register", TimeSpan.FromSeconds(90));
        // Show each client's result up front: success for one client must not hide
        // that the other (usually Claude Desktop) was not found.
        var lines = output.Split('\n').Select(l => l.TrimEnd()).Where(l => l.StartsWith("[")).ToList();
        var desktopOk = lines.Any(l => l.StartsWith("[ok] Claude Desktop"));
        var td = new TaskDialog(Product.Name)
        {
            MainInstruction = desktopOk ? "Revit MCP is registered with Claude Desktop."
                : code == 0 ? "Registered, but not with Claude Desktop."
                : "Registration did not complete.",
            MainContent = (lines.Count > 0 ? string.Join("\n", lines) : "(no output)") + "\n\n" +
                (desktopOk
                    ? "Fully quit Claude Desktop (tray icon > Quit) and open it again to load the Revit tools."
                    : "Install Claude Desktop from claude.ai/download and open it once, then click Connect Claude again."),
            ExpandedContent = output.Length > 0 ? output : "(no output)",
            CommonButtons = TaskDialogCommonButtons.Close,
        };
        td.Show();
        return Result.Succeeded;
    }
}

/// <summary>Pause or resume the connection (button text follows the state).</summary>
[Transaction(TransactionMode.ReadOnly)]
public sealed class PauseResumeCommand : IExternalCommand
{
    public Result Execute(ExternalCommandData commandData, ref string message, ElementSet elements)
    {
        var app = RevitMcpApp.Current;
        if (app == null) { message = "Revit MCP is not running."; return Result.Failed; }
        try
        {
            if (app.IsRunning)
            {
                app.StopServer();
                AddinLog.Info("Paused from the ribbon.");
            }
            else
            {
                app.StartServer();
                AddinLog.Info("Resumed from the ribbon.");
            }
        }
        catch (Exception ex)
        {
            AddinLog.Error("Pause/resume failed", ex);
            TaskDialog.Show(Product.Name, $"Could not change the connection state: {ex.Message}");
        }
        Ribbon.RefreshPauseButton();
        return Result.Succeeded;
    }
}

/// <summary>Latest audit records plus a tamper check.</summary>
[Transaction(TransactionMode.ReadOnly)]
public sealed class AuditLogCommand : IExternalCommand
{
    public Result Execute(ExternalCommandData commandData, ref string message, ElementSet elements)
    {
        var path = AuditLog.Path;
        AuditReader.Result r;
        try { r = AuditReader.Read(path, latest: 12); }
        catch (Exception ex)
        {
            TaskDialog.Show(Product.Name, $"Could not read the audit log at {path}: {ex.Message}");
            return Result.Succeeded;
        }

        var td = new TaskDialog(Product.Name)
        {
            MainInstruction = r.Ok ? "Audit log" : "Audit log: tampering detected",
            MainContent = r.Message + (r.Latest.Count > 0 ? "\n\nLatest first:\n" + string.Join("\n", r.Latest) : ""),
            FooterText = path,
            CommonButtons = TaskDialogCommonButtons.Close,
        };
        if (File.Exists(path)) td.AddCommandLink(TaskDialogCommandLinkId.CommandLink1, "Open the full log", "Plain text, one record per line.");
        td.AddCommandLink(TaskDialogCommandLinkId.CommandLink2, "Open the audit folder");

        var choice = td.Show();
        if (choice == TaskDialogResult.CommandLink1) Shell.OpenWithNotepad(path);
        else if (choice == TaskDialogResult.CommandLink2) Shell.OpenFolder(Path.GetDirectoryName(path)!);
        return Result.Succeeded;
    }
}

[Transaction(TransactionMode.ReadOnly)]
public sealed class HelpCommand : IExternalCommand
{
    public Result Execute(ExternalCommandData commandData, ref string message, ElementSet elements)
    {
        var help = Product.HelpFile;
        if (help != null) Shell.Open(help);
        else TaskDialog.Show(Product.Name, "The help page is installed with the Revit MCP product (MSI). In a developer deploy, see the repo's docs folder.");
        return Result.Succeeded;
    }
}

[Transaction(TransactionMode.ReadOnly)]
public sealed class OpenLogsCommand : IExternalCommand
{
    public Result Execute(ExternalCommandData commandData, ref string message, ElementSet elements)
    {
        Directory.CreateDirectory(Product.LogDirectory);
        Shell.OpenFolder(Product.LogDirectory);
        return Result.Succeeded;
    }
}

/// <summary>Small helpers for opening files/folders and running the server exe.</summary>
internal static class Shell
{
    public static void Open(string path)
    {
        try { Process.Start(new ProcessStartInfo(path) { UseShellExecute = true }); }
        catch (Exception ex) { AddinLog.Warn($"Could not open {path}: {ex.Message}"); }
    }

    public static void OpenFolder(string folder)
    {
        try { Process.Start(new ProcessStartInfo("explorer.exe", $"\"{folder}\"") { UseShellExecute = true }); }
        catch (Exception ex) { AddinLog.Warn($"Could not open folder {folder}: {ex.Message}"); }
    }

    public static void OpenWithNotepad(string file)
    {
        try { Process.Start(new ProcessStartInfo("notepad.exe", $"\"{file}\"") { UseShellExecute = true }); }
        catch (Exception ex) { AddinLog.Warn($"Could not open {file}: {ex.Message}"); }
    }

    public static void CopyToClipboard(string text)
    {
        try { System.Windows.Clipboard.SetText(text); }
        catch (Exception ex) { AddinLog.Warn($"Clipboard copy failed: {ex.Message}"); }
    }

    /// <summary>Run a console program without a window; returns (exit code, stdout+stderr).</summary>
    public static (int Code, string Output) Run(string exe, string args, TimeSpan timeout)
    {
        try
        {
            var psi = new ProcessStartInfo(exe, args)
            {
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                StandardOutputEncoding = Encoding.UTF8,
                StandardErrorEncoding = Encoding.UTF8,
            };
            using var p = Process.Start(psi)!;
            var stdout = p.StandardOutput.ReadToEndAsync();
            var stderr = p.StandardError.ReadToEndAsync();
            if (!p.WaitForExit((int)timeout.TotalMilliseconds))
            {
                try { p.Kill(entireProcessTree: true); } catch { }
                return (-1, $"Timed out after {timeout.TotalSeconds:0} s.");
            }
            var output = (stdout.Result + stderr.Result).Trim();
            AddinLog.Info($"Ran {Path.GetFileName(exe)} {args}: exit {p.ExitCode}");
            return (p.ExitCode, output);
        }
        catch (Exception ex)
        {
            AddinLog.Error($"Could not run {exe}", ex);
            return (-1, ex.Message);
        }
    }
}
