using Autodesk.Revit.UI;
using RevitMCP.Addin.Diagnostics;
using Color = System.Windows.Media.Color;

namespace RevitMCP.Addin.UI;

/// <summary>
/// The "Revit MCP" ribbon tab:
///
///   Claude connection: Status | Connect Claude | Pause/Resume
///   Records:           Audit log
///   Support:           Help | Logs
///
/// All buttons work with no document open (<see cref="AlwaysAvailable"/>).
/// F1 on any button opens the bundled help page.
/// </summary>
public static class Ribbon
{
    public const string TabName = "Revit MCP";
    private static PushButton? _pauseButton;

    public static void Create(UIControlledApplication app)
    {
        try { app.CreateRibbonTab(TabName); }
        catch (Autodesk.Revit.Exceptions.ArgumentException) { /* tab already exists */ }

        var connection = app.CreateRibbonPanel(TabName, "Claude connection");
        Add(connection, "RevitMCP.Status", "Status", typeof(StatusCommand), Icons.Status, Icons.Blue,
            "Show whether Claude can reach this Revit session.",
            "Shows the add-in version, whether the connection is running or paused, whether a Claude client is connected and with what access, and where the audit log and support logs are.");
        Add(connection, "RevitMCP.Connect", "Connect\nClaude", typeof(ConnectClaudeCommand), Icons.Link, Icons.Purple,
            "Register Revit MCP with Claude Desktop and Claude Code on this PC.",
            "The installer does this once. Use it again after installing Claude Desktop or Claude Code, or if Claude no longer lists the Revit tools. Restart Claude afterwards.");
        _pauseButton = Add(connection, "RevitMCP.Pause", "Pause", typeof(PauseResumeCommand), Icons.Pause, Icons.Amber,
            "Stop Claude from reaching this Revit session until you resume.",
            "Disconnects the Claude client and stops listening. Nothing in the model changes. Resume starts a new session with a new access token.");

        var records = app.CreateRibbonPanel(TabName, "Records");
        Add(records, "RevitMCP.Audit", "Audit\nlog", typeof(AuditLogCommand), Icons.Document, Icons.Green,
            "Who approved each change made through Claude, and when.",
            "Shows the latest committed, undone and refused changes from the tamper-evident audit log, and checks that the log has not been edited.");

        var support = app.CreateRibbonPanel(TabName, "Support");
        Add(support, "RevitMCP.Help", "Help", typeof(HelpCommand), Icons.Help, Icons.Slate,
            "Open the Revit MCP help page.", null);
        Add(support, "RevitMCP.Logs", "Logs", typeof(OpenLogsCommand), Icons.Folder, Icons.Slate,
            "Open the folder with Revit MCP support logs.",
            "Attach these logs when you contact support.");

        RefreshPauseButton();
        AddinLog.Info("Ribbon tab created.");
    }

    /// <summary>Show Pause or Resume to match the server state.</summary>
    public static void RefreshPauseButton()
    {
        if (_pauseButton == null) return;
        var running = RevitMcpApp.Current?.IsRunning == true;
        _pauseButton.ItemText = running ? "Pause" : "Resume";
        _pauseButton.ToolTip = running
            ? "Stop Claude from reaching this Revit session until you resume."
            : "Let Claude reach this Revit session again.";
        var (glyph, color) = running ? (Icons.Pause, Icons.Amber) : (Icons.Play, Icons.Green);
        _pauseButton.LargeImage = Icons.Tile(glyph, color, 32);
        _pauseButton.Image = Icons.Tile(glyph, color, 16);
    }

    private static PushButton Add(RibbonPanel panel, string name, string text, Type command,
        string glyph, Color color, string tooltip, string? longDescription)
    {
        var data = new PushButtonData(name, text, command.Assembly.Location, command.FullName)
        {
            ToolTip = tooltip,
            LargeImage = Icons.Tile(glyph, color, 32),
            Image = Icons.Tile(glyph, color, 16),
            AvailabilityClassName = typeof(AlwaysAvailable).FullName,
        };
        if (!string.IsNullOrEmpty(longDescription)) data.LongDescription = longDescription;

        var help = Product.HelpFile;
        if (help != null) data.SetContextualHelp(new ContextualHelp(ContextualHelpType.Url, new Uri(help).AbsoluteUri));

        return (PushButton)panel.AddItem(data);
    }
}

/// <summary>Ribbon buttons are usable with no document open (zero-doc state).</summary>
public sealed class AlwaysAvailable : IExternalCommandAvailability
{
    public bool IsCommandAvailable(UIApplication applicationData, Autodesk.Revit.DB.CategorySet selectedCategories) => true;
}
