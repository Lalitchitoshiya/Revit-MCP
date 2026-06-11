using Autodesk.Revit.DB;
using RevitMCP.Addin.Plans;
using RevitMCP.Addin.Protocol;

namespace RevitMCP.Addin.Commands;

/// <summary>
/// `plan.undo` (docs/04 §4.2, FR-P5). Reverts a committed plan by deleting the
/// elements it created, in a single transaction (itself one undo step). Defaults
/// to the most recently committed plan when no id is given.
/// </summary>
public sealed class PlanUndoCommand : DocumentCommand
{
    public override string Method => "plan.undo";

    protected override RpcResponse ExecuteOnDocument(DocumentContext ctx, RpcRequest request)
    {
        var planId = request.Params.TryGetProperty("plan_id", out var pid) ? pid.GetString() : null;
        planId ??= PlanRegistry.LastCommittedPlanId;

        if (string.IsNullOrEmpty(planId) || !PlanRegistry.TryGetCommitted(planId, out var ids))
        {
            return RpcResponse.Failure(request.Id, "PLAN_NOT_FOUND",
                "No committed plan to undo for that id.",
                "Undo applies to plans committed in this session. Use Revit's own Undo otherwise.");
        }

        var doc = ctx.Doc;
        var deleted = new List<long>();

        using (var t = new Transaction(doc, $"RevitMCP: undo {planId}"))
        {
            t.Start();
            foreach (var id in ids)
            {
                if (doc.GetElement(id) == null) continue; // already gone
                foreach (var d in doc.Delete(id)) deleted.Add(d.Value);
            }
            t.Commit();
        }

        PlanRegistry.RemoveCommitted(planId!);
        return RpcResponse.Success(request.Id, new { plan_id = planId, undone = true, deleted_count = deleted.Count });
    }
}
