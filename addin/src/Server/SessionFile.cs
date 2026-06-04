using System.Security.AccessControl;
using System.Security.Principal;
using System.Text.Json;
using RevitMCP.Addin.Diagnostics;
using RevitMCP.Addin.Protocol;

namespace RevitMCP.Addin.Server;

/// <summary>
/// Writes %LOCALAPPDATA%\RevitMCP\session.json (docs/06 §6.7), read by the
/// Python MCP server to discover the port and auth token. Best-effort ACL
/// hardening restricts the file to the current user (NFR-3).
/// </summary>
public static class SessionFile
{
    public static string Path => System.IO.Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "RevitMCP", "session.json");

    public static void Write(int port, string token, string? revitVersion)
    {
        var dir = System.IO.Path.GetDirectoryName(Path)!;
        Directory.CreateDirectory(dir);

        var payload = new
        {
            port,
            token,
            protocol_version = Wire.ProtocolVersion,
            revit_version = revitVersion,
            pid = Environment.ProcessId,
        };

        File.WriteAllText(Path, JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true }));
        TryRestrictToCurrentUser(Path);
        AddinLog.Info($"Wrote session file: {Path} (port={port})");
    }

    public static void Delete()
    {
        try { if (File.Exists(Path)) File.Delete(Path); }
        catch (Exception ex) { AddinLog.Warn($"Could not delete session file: {ex.Message}"); }
    }

    private static void TryRestrictToCurrentUser(string path)
    {
        try
        {
            var fi = new FileInfo(path);
            var security = new FileSecurity();
            var user = WindowsIdentity.GetCurrent().User!;
            security.SetOwner(user);
            security.SetAccessRuleProtection(isProtected: true, preserveInheritance: false);
            security.AddAccessRule(new FileSystemAccessRule(
                user, FileSystemRights.FullControl, AccessControlType.Allow));
            fi.SetAccessControl(security);
        }
        catch (Exception ex)
        {
            // Non-fatal: the loopback bind + token still gate access.
            AddinLog.Warn($"Could not harden session file ACL: {ex.Message}");
        }
    }
}
