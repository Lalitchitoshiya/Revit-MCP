using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace RevitMCP.Addin.Plans;

/// <summary>A parsed plan (docs/06 §6.2). Carries a content hash so a commit can
/// be checked against what was previewed (docs/05 §5.4).</summary>
public sealed class PlanNode
{
    public string? Intent { get; init; }
    public string? DefaultUnit { get; init; }
    public List<ActionNode> Actions { get; init; } = new();
    public string Hash { get; init; } = "";

    public static PlanNode Parse(JsonElement planEl)
    {
        var actions = new List<ActionNode>();
        if (planEl.TryGetProperty("actions", out var arr) && arr.ValueKind == JsonValueKind.Array)
        {
            var i = 0;
            foreach (var a in arr.EnumerateArray())
            {
                actions.Add(new ActionNode
                {
                    Index = i++,
                    Op = a.TryGetProperty("op", out var op) ? op.GetString() ?? "" : "",
                    Handle = a.TryGetProperty("handle", out var h) ? h.GetString() : null,
                    Params = a.TryGetProperty("params", out var p) ? p.Clone() : default,
                });
            }
        }

        return new PlanNode
        {
            Intent = planEl.TryGetProperty("intent", out var it) ? it.GetString() : null,
            DefaultUnit = planEl.TryGetProperty("default_unit", out var du) ? du.GetString() : null,
            Actions = actions,
            Hash = HashOf(planEl),
        };
    }

    /// <summary>Stable hash of the plan's raw JSON text (docs/05 §5.4).</summary>
    private static string HashOf(JsonElement planEl)
    {
        var bytes = SHA256.HashData(Encoding.UTF8.GetBytes(planEl.GetRawText()));
        return Convert.ToHexString(bytes).ToLowerInvariant();
    }
}

/// <summary>One typed operation in a plan (docs/06 §6.3).</summary>
public sealed class ActionNode
{
    public int Index { get; init; }
    public string Op { get; init; } = "";
    public string? Handle { get; init; }
    public JsonElement Params { get; init; }
}

/// <summary>A validation diagnostic (docs/06 §6.5).</summary>
public sealed class Diagnostic
{
    public string Severity { get; init; } = "error";
    public string Code { get; init; } = "";
    public string Message { get; init; } = "";
    public string? Hint { get; init; }

    public static Diagnostic Error(string code, string message, string? hint = null) =>
        new() { Severity = "error", Code = code, Message = message, Hint = hint };

    public static Diagnostic Warning(string code, string message, string? hint = null) =>
        new() { Severity = "warning", Code = code, Message = message, Hint = hint };

    public static Diagnostic Info(string code, string message) =>
        new() { Severity = "info", Code = code, Message = message };
}

/// <summary>Canonical diagnostic codes (docs/06 §6.5).</summary>
public static class DiagCodes
{
    public const string MissingField = "MISSING_FIELD";
    public const string UnknownType = "UNKNOWN_TYPE";
    public const string UnknownLevel = "UNKNOWN_LEVEL";
    public const string FamilyNotLoaded = "FAMILY_NOT_LOADED";
    public const string AmbiguousRef = "AMBIGUOUS_REF";
    public const string HostMissing = "HOST_MISSING";
    public const string HostWrongCategory = "HOST_WRONG_CATEGORY";
    public const string RoomNotEnclosed = "ROOM_NOT_ENCLOSED";
    public const string InvalidBoundary = "INVALID_BOUNDARY";
    public const string UnitlessLength = "UNITLESS_LENGTH";
    public const string ZeroLength = "ZERO_LENGTH";
    public const string WallVeryShort = "WALL_VERY_SHORT";
    public const string InvalidGeometry = "INVALID_GEOMETRY";
    public const string UnknownOp = "UNKNOWN_OP";
}

/// <summary>Outcome of previewing one action (docs/04 §4.2 preview_plan).</summary>
public sealed class ActionPreview
{
    public List<Diagnostic> Diagnostics { get; } = new();
    public object? Resolved { get; set; }
    public object? Preview { get; set; }

    public bool HasError => Diagnostics.Any(d => d.Severity == "error");
    public bool HasWarning => Diagnostics.Any(d => d.Severity == "warning");
    public string Status => HasError ? "error" : HasWarning ? "warning" : "ok";

    public void Add(Diagnostic d) => Diagnostics.Add(d);
}
