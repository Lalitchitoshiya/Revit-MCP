using System.Text.Json;
using Autodesk.Revit.DB;
using RevitMCP.Addin.Commands;
using RevitMCP.Addin.Plans;
using RevitMCP.Addin.Protocol;

namespace RevitMCP.Addin.Audit;

/// <summary>Builds the common fields of a plan.commit / plan.undo audit record.</summary>
public static class AuditRecord
{
    public static Dictionary<string, object?> ForPlan(DocumentContext ctx, RpcRequest request, string? planId)
    {
        var p = request.Params;
        var doc = ctx.Doc;
        string? revitUser = null;
        try { revitUser = ctx.App.Application.Username; } catch { /* optional */ }

        return new Dictionary<string, object?>
        {
            ["plan_id"] = planId,
            ["intent"] = TryGetPlan(p, out var plan) && plan.TryGetProperty("intent", out var i) &&
                         i.ValueKind == JsonValueKind.String ? i.GetString() : null,
            ["summary"] = p.ValueKind == JsonValueKind.Object && p.TryGetProperty("summary", out var s) &&
                          s.ValueKind == JsonValueKind.String ? s.GetString() : null,
            // Forwarded by the MCP server: who approved, when, how (human-verified or not).
            // Absent = the caller bypassed the server's approval step — visible here.
            ["approval"] = p.ValueKind == JsonValueKind.Object && p.TryGetProperty("approval", out var a) &&
                           a.ValueKind == JsonValueKind.Object ? a.Clone() : null,
            ["principal"] = request.Principal?.ToAudit(),
            ["document"] = new { title = doc.Title, path = doc.PathName, key = PlanRegistry.DocKey(doc) },
            ["revit_user"] = revitUser,
            ["os_user"] = Environment.UserName,
            ["machine"] = Environment.MachineName,
        };
    }

    public static object OpCounts(PlanNode plan) =>
        plan.Actions.GroupBy(a => string.IsNullOrEmpty(a.Op) ? "?" : a.Op).ToDictionary(g => g.Key, g => g.Count());

    private static bool TryGetPlan(JsonElement p, out JsonElement plan)
    {
        plan = default;
        return p.ValueKind == JsonValueKind.Object && p.TryGetProperty("plan", out plan) &&
               plan.ValueKind == JsonValueKind.Object;
    }
}
