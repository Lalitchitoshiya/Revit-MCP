using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using RevitMCP.Addin.Diagnostics;

namespace RevitMCP.Addin.Audit;

/// <summary>
/// Append-only, hash-chained approval audit log (one JSON object per line):
///
///   %LOCALAPPDATA%\RevitMCP\audit\audit.jsonl   (override: REVIT_MCP_AUDIT)
///
/// Each line is {"seq","ts","prev_hash", ...record..., "hash"} where
/// hash = SHA-256 of the exact line bytes without the trailing ,"hash":"…".
/// Editing, deleting or reordering a line breaks the chain from there on;
/// `python -m revit_mcp.audit verify` checks it. This add-in is the single
/// writer — it is the component that actually changes the model.
///
/// Thread-safe: commits/undos append from the UI thread, auth denials from the
/// socket thread.
/// </summary>
public static class AuditLog
{
    private const string Genesis = "0000000000000000000000000000000000000000000000000000000000000000";
    private static readonly object Gate = new();
    private static bool _initialized;
    private static long _seq;
    private static string _prevHash = Genesis;

    public static string Path =>
        Environment.GetEnvironmentVariable("REVIT_MCP_AUDIT") is { Length: > 0 } p
            ? p
            : System.IO.Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "RevitMCP", "audit", "audit.jsonl");

    /// <summary>
    /// Check the log can be written BEFORE changing the model, so a change is
    /// never made that cannot be recorded. Returns an error message or null.
    /// </summary>
    public static string? CheckWritable()
    {
        try
        {
            lock (Gate)
            {
                EnsureInitialized();
                using var _ = new FileStream(Path, FileMode.Append, FileAccess.Write, FileShare.Read);
            }
            return null;
        }
        catch (Exception ex)
        {
            AddinLog.Error("Audit log not writable", ex);
            return $"Audit log at {Path} is not writable: {ex.Message}";
        }
    }

    /// <summary>Append one record. Never throws (failures are logged).</summary>
    public static bool Append(string evt, string outcome, object record)
    {
        try
        {
            lock (Gate)
            {
                EnsureInitialized();
                var obj = new JsonObject
                {
                    ["seq"] = _seq + 1,
                    ["ts"] = DateTimeOffset.UtcNow.ToString("yyyy-MM-dd'T'HH:mm:ss.fff'+00:00'"),
                    ["prev_hash"] = _prevHash,
                    ["event"] = evt,
                    ["outcome"] = outcome,
                };
                if (JsonSerializer.SerializeToNode(record) is JsonObject rec)
                {
                    foreach (var (k, v) in rec.ToList())
                    {
                        rec.Remove(k);
                        if (!obj.ContainsKey(k)) obj[k] = v;
                    }
                }

                var body = obj.ToJsonString();
                var hash = Sha256Hex(body);
                var line = body[..^1] + ",\"hash\":\"" + hash + "\"}\n";
                using (var fs = new FileStream(Path, FileMode.Append, FileAccess.Write, FileShare.Read))
                {
                    var bytes = new UTF8Encoding(false).GetBytes(line);
                    fs.Write(bytes, 0, bytes.Length);
                    fs.Flush(flushToDisk: true);
                }
                _seq++;
                _prevHash = hash;
                return true;
            }
        }
        catch (Exception ex)
        {
            AddinLog.Error($"Failed to write audit record ({evt}/{outcome})", ex);
            return false;
        }
    }

    /// <summary>Recover seq + last hash from the tail of an existing log.</summary>
    private static void EnsureInitialized()
    {
        if (_initialized) return;
        Directory.CreateDirectory(System.IO.Path.GetDirectoryName(Path)!);
        if (File.Exists(Path))
        {
            var last = ReadLastLine(Path);
            if (last != null)
            {
                using var doc = JsonDocument.Parse(last);
                _seq = doc.RootElement.GetProperty("seq").GetInt64();
                _prevHash = doc.RootElement.GetProperty("hash").GetString() ?? Genesis;
            }
        }
        _initialized = true;
        AddinLog.Info($"Audit log: {Path} (next seq {_seq + 1})");
    }

    private static string? ReadLastLine(string path)
    {
        using var fs = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
        if (fs.Length == 0) return null;
        // Read backwards in growing chunks until we have one complete last line.
        for (long chunk = 64 * 1024; ; chunk *= 4)
        {
            var start = Math.Max(0, fs.Length - chunk);
            fs.Seek(start, SeekOrigin.Begin);
            var buf = new byte[fs.Length - start];
            fs.ReadExactly(buf);
            var text = Encoding.UTF8.GetString(buf).TrimEnd('\n', '\r');
            var nl = text.LastIndexOf('\n');
            if (nl >= 0 || start == 0)
                return text[(nl + 1)..] is { Length: > 0 } l ? l : null;
        }
    }

    private static string Sha256Hex(string s) =>
        Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(s))).ToLowerInvariant();
}
