using System.Text.Json;
using Autodesk.Revit.DB;
using RevitMCP.Addin.Plans;
using RevitMCP.Addin.Plans.Actions;
using RevitMCP.Addin.Protocol;
using RevitMCP.Addin.Revit;

namespace RevitMCP.Addin.Commands;

/// <summary>
/// `plan.preview` (docs/04 §4.2, docs/05 §5.4). Validates a plan READ-ONLY
/// against the live model and reports what would happen. Marks the plan hash as
/// previewed so it may later be committed. Opens no transaction (NFR-2/§3.3).
/// </summary>
public sealed class PlanPreviewCommand : DocumentCommand
{
    public override string Method => "plan.preview";

    protected override RpcResponse ExecuteOnDocument(DocumentContext ctx, RpcRequest request)
    {
        if (!request.Params.TryGetProperty("plan", out var planEl))
            return RpcResponse.Failure(request.Id, ErrorCodes.InvalidParams, "Missing 'plan'.");

        var doc = ctx.Doc;
        var u = DocUnits.From(doc);
        var plan = PlanNode.Parse(planEl);
        var emptyHandles = new Dictionary<string, ElementId>();

        var actions = new List<object>();
        var anyError = false;
        var anyWarning = false;

        foreach (var action in plan.Actions)
        {
            ActionPreview preview;
            if (!ActionHandlers.TryGet(action.Op, out var handler))
            {
                preview = new ActionPreview();
                preview.Add(Diagnostic.Error(DiagCodes.UnknownOp, $"Unknown op '{action.Op}'."));
            }
            else
            {
                try
                {
                    preview = handler.Preview(doc, u, action, emptyHandles);
                }
                catch (Exception ex)
                {
                    preview = new ActionPreview();
                    preview.Add(Diagnostic.Error(DiagCodes.InvalidGeometry, ex.Message));
                }
            }

            anyError |= preview.HasError;
            anyWarning |= preview.HasWarning;
            actions.Add(new
            {
                index = action.Index,
                op = action.Op,
                status = preview.Status,
                resolved = preview.Resolved,
                preview = preview.Preview,
                diagnostics = preview.Diagnostics.Select(Serialize).ToList(),
            });
        }

        // Only a clean (commit-eligible) plan is remembered as previewed.
        if (!anyError) PlanRegistry.MarkPreviewed(plan.Hash);

        var overall = anyError ? "errors" : anyWarning ? "warnings" : "ok";
        var result = new
        {
            plan_hash = plan.Hash,
            overall,
            actions,
            summary = Summarize(plan, overall),
        };
        return RpcResponse.Success(request.Id, result);
    }

    private static object Serialize(Diagnostic d) =>
        new { severity = d.Severity, code = d.Code, message = d.Message, hint = d.Hint };

    private static string Summarize(PlanNode plan, string overall)
    {
        var walls = plan.Actions.Count(a => a.Op == "place_wall");
        if (overall == "errors") return "Plan has errors and cannot be committed as-is.";
        var parts = new List<string>();
        if (walls > 0) parts.Add($"{walls} wall{(walls == 1 ? "" : "s")}");
        var what = parts.Count > 0 ? string.Join(", ", parts) : $"{plan.Actions.Count} action(s)";
        return $"Would create {what}.";
    }
}
