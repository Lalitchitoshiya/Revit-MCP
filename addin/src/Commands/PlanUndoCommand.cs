using Autodesk.Revit.DB;
using RevitMCP.Addin.Audit;
using RevitMCP.Addin.Plans;
using RevitMCP.Addin.Protocol;

namespace RevitMCP.Addin.Commands;

/// <summary>
/// `plan.undo` (docs/04 §4.2, FR-P5). Reverts a committed plan by deleting the
/// elements it created, in a single transaction (itself one undo step). Defaults
/// to the most recently committed plan when no id is given. Refuses to run
/// against a different document than the one the plan was committed to, and
/// writes an audit record (with approval) for every attempt that gets that far.
/// </summary>
public sealed class PlanUndoCommand : DocumentCommand
{
    public override string Method => "plan.undo";

    protected override RpcResponse ExecuteOnDocument(DocumentContext ctx, RpcRequest request)
    {
        var planId = request.Params.TryGetProperty("plan_id", out var pid) ? pid.GetString() : null;
        planId ??= PlanRegistry.LastCommittedPlanId;

        if (string.IsNullOrEmpty(planId) || !PlanRegistry.TryGetCommitted(planId, out var docKey, out var ids))
        {
            return RpcResponse.Failure(request.Id, "PLAN_NOT_FOUND",
                "No committed plan to undo for that id.",
                "Undo applies to plans committed in this Revit session. Use Revit's own Undo otherwise.");
        }

        var doc = ctx.Doc;
        var audit = AuditRecord.ForPlan(ctx, request, planId);

        if (PlanRegistry.DocKey(doc) != docKey)
        {
            var msg = $"Plan {planId} was committed to '{docKey}', but the active document is '{PlanRegistry.DocKey(doc)}'.";
            audit["error"] = new { code = "WRONG_DOCUMENT", message = msg };
            AuditLog.Append("plan.undo", "refused", audit);
            return RpcResponse.Failure(request.Id, "WRONG_DOCUMENT", msg,
                "Switch to that document in Revit, then retry the undo.");
        }
        if (AuditLog.CheckWritable() is string auditProblem)
            return RpcResponse.Failure(request.Id, ErrorCodes.AuditUnavailable, auditProblem,
                "Fix the audit log location/permissions, then retry. Nothing was removed.");

        var deleted = new List<long>();
        using (var t = new Transaction(doc, $"RevitMCP: undo {planId}"))
        {
            t.Start();
            SilentFailureHandler.Apply(t);
            foreach (var id in ids)
            {
                if (doc.GetElement(id) == null) continue; // already gone
                foreach (var d in doc.Delete(id)) deleted.Add(d.Value);
            }
            t.Commit();
        }

        PlanRegistry.RemoveCommitted(planId!);
        audit["plan_element_ids"] = ids.Select(i => i.Value).ToList();
        audit["deleted_ids"] = deleted; // includes dependents Revit removed with them
        var audited = AuditLog.Append("plan.undo", "undone", audit);
        return RpcResponse.Success(request.Id, new
        {
            plan_id = planId, undone = true, deleted_count = deleted.Count, audited,
        });
    }
}
