using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace RevitMCP.Addin.Audit;

/// <summary>
/// Read side of the audit log for the ribbon: verify the hash chain (same rule
/// as server/revit_mcp/audit.py verify) and summarise the latest records.
/// </summary>
public static class AuditReader
{
    private static readonly Regex LineRe = new(@"^(.*),""hash"":""([0-9a-f]{64})""\}$", RegexOptions.Compiled);

    public sealed record Result(bool Ok, int Count, string Message, IReadOnlyList<string> Latest);

    public static Result Read(string path, int latest)
    {
        if (!File.Exists(path)) return new Result(true, 0, "No changes have been recorded yet.", Array.Empty<string>());

        string[] lines;
        using (var fs = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
        using (var reader = new StreamReader(fs, Encoding.UTF8))
            lines = reader.ReadToEnd().Split('\n');

        var prev = new string('0', 64);
        var n = 0;
        var summaries = new List<string>();
        string? problem = null;
        for (var i = 0; i < lines.Length; i++)
        {
            var line = lines[i].TrimEnd('\r');
            if (line.Trim().Length == 0) continue;
            var m = LineRe.Match(line);
            if (!m.Success) { problem ??= $"line {i + 1} has no hash (edited or truncated)"; continue; }
            var body = m.Groups[1].Value + "}";
            var claimed = m.Groups[2].Value;
            if (problem == null && Sha256(body) != claimed) problem = $"line {i + 1} was edited after it was written";
            try
            {
                using var doc = JsonDocument.Parse(body);
                var root = doc.RootElement;
                if (problem == null && Str(root, "prev_hash") != prev)
                    problem = $"a record before line {i + 1} was removed or reordered";
                summaries.Add(Summarise(root));
            }
            catch (JsonException) { problem ??= $"line {i + 1} is not valid JSON"; }
            prev = claimed;
            n++;
        }

        var latestList = summaries.Skip(Math.Max(0, summaries.Count - latest)).Reverse().ToList();
        return problem == null
            ? new Result(true, n, $"{n} record(s); the log has not been edited.", latestList)
            : new Result(false, n, $"WARNING: the audit log has been tampered with: {problem}.", latestList);
    }

    private static string Summarise(JsonElement r)
    {
        var ts = Str(r, "ts") ?? "";
        if (DateTimeOffset.TryParse(ts, out var when)) ts = when.ToLocalTime().ToString("yyyy-MM-dd HH:mm");
        var evt = Str(r, "event") ?? "?";
        var outcome = Str(r, "outcome") ?? "?";

        var who = "";
        if (r.TryGetProperty("approval", out var ap) && ap.ValueKind == JsonValueKind.Object)
        {
            var by = Str(ap, "approved_by");
            var human = ap.TryGetProperty("human_verified", out var hv) && hv.ValueKind == JsonValueKind.True;
            if (by != null) who = $" by {by}{(human ? "" : " (not human-verified)")}";
        }
        else if (r.TryGetProperty("principal", out var pr) && pr.ValueKind == JsonValueKind.Object && Str(pr, "sub") is { } sub)
        {
            who = $" token {sub}";
        }

        var what = Str(r, "summary") ?? Str(r, "intent") ?? Str(r, "method") ?? Str(r, "code") ?? "";
        if (what.Length > 90) what = what[..87] + "...";
        return $"{ts}  {evt} {outcome}{who}{(what.Length > 0 ? " - " + what : "")}";
    }

    private static string? Str(JsonElement e, string name) =>
        e.TryGetProperty(name, out var v) && v.ValueKind == JsonValueKind.String ? v.GetString() : null;

    private static string Sha256(string s) =>
        Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(s))).ToLowerInvariant();
}
