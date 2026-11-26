using System.Text.Json;
using Autodesk.Revit.DB;
using RevitMCP.Addin.Audit;
using RevitMCP.Addin.Plans;
using RevitMCP.Addin.Plans.Actions;
using RevitMCP.Addin.Protocol;
using RevitMCP.Addin.Revit;

namespace RevitMCP.Addin.Commands;

/// <summary>
/// `plan.commit` (docs/04 §4.2, docs/05 §5.4, FR-P3/P6). Executes a previewed
/// plan inside ONE TransactionGroup so the whole batch is a single undo step and
/// any failure rolls back everything (atomic).
///
/// Every outcome — committed, refused, or failed+rolled back — is written to the
/// audit log with the approval metadata forwarded by the MCP server and the
/// verified caller identity. If the audit log cannot be written, nothing is
/// committed.
/// </summary>
public sealed class PlanCommitCommand : DocumentCommand
{
    public override string Method => "plan.commit";

    protected override RpcResponse ExecuteOnDocument(DocumentContext ctx, RpcRequest request)
    {
        var p = request.Params;
        if (!p.TryGetProperty("plan", out var planEl))
            return RpcResponse.Failure(request.Id, ErrorCodes.InvalidParams, "Missing 'plan'.");
        var planId = p.TryGetProperty("plan_id", out var pid) ? pid.GetString() : null;
        if (string.IsNullOrEmpty(planId))
            return RpcResponse.Failure(request.Id, ErrorCodes.InvalidParams, "Missing 'plan_id'.");
        var providedHash = p.TryGetProperty("plan_hash", out var ph) ? ph.GetString() : null;

        var doc = ctx.Doc;
        var u = DocUnits.From(doc);
        var plan = PlanNode.Parse(planEl);

        var audit = AuditRecord.ForPlan(ctx, request, planId);
        audit["plan_hash"] = plan.Hash;
        audit["ops"] = AuditRecord.OpCounts(plan);

        RpcResponse Refuse(string code, string message, string? hint = null)
        {
            audit["error"] = new { code, message };
            AuditLog.Append("plan.commit", "refused", audit);
            return RpcResponse.Failure(request.Id, code, message, hint);
        }

        // Commit hygiene (docs/05 §5.5): must match what was previewed, in this document.
        if (providedHash != null && providedHash != plan.Hash)
            return Refuse("PLAN_CHANGED_SINCE_PREVIEW",
                "The plan differs from the one previewed.", "Preview again before committing.");
        if (!PlanRegistry.IsPreviewed(doc, plan.Hash))
            return Refuse("PLAN_NOT_PREVIEWED",
                "This plan was not previewed in the active document (or preview had errors, or it was already committed).",
                "Call preview_plan first.");

        // Never change the model if the change cannot be recorded.
        if (AuditLog.CheckWritable() is string auditProblem)
            return RpcResponse.Failure(request.Id, ErrorCodes.AuditUnavailable, auditProblem,
                "Fix the audit log location/permissions, then retry. Nothing was committed.");

        // Re-validate read-only; never open a transaction for an error-laden plan.
        var handleCategories = new Dictionary<string, string>(StringComparer.Ordinal);
        for (var i = 0; i < plan.Actions.Count; i++)
        {
            var act = plan.Actions[i];
            if (!ActionHandlers.TryGet(act.Op, out var h))
                return Refuse("ACTION_FAILED", $"Unknown op '{act.Op}'.");
            var pre = h.Preview(doc, u, act, handleCategories);
            if (pre.HasError)
                return Refuse("PLAN_HAS_ERRORS", $"Action {i} ('{act.Op}') has errors; not committed.");
            if (!string.IsNullOrEmpty(act.Handle)) handleCategories[act.Handle!] = h.ProducedCategory;
        }

        var handles = new Dictionary<string, ElementId>();
        var created = new List<object>();
        var createdIds = new List<ElementId>();

        RpcResponse Fail(string message)
        {
            audit["error"] = new { code = "ACTION_FAILED", message };
            AuditLog.Append("plan.commit", "failed_rolled_back", audit);
            return RpcResponse.Failure(request.Id, "ACTION_FAILED", message);
        }

        using var group = new TransactionGroup(doc, Truncate($"RevitMCP: {plan.Intent ?? "place"}", 240));
        group.Start();

        for (var i = 0; i < plan.Actions.Count; i++)
        {
            var action = plan.Actions[i];
            ActionHandlers.TryGet(action.Op, out var handler);
            using var t = new Transaction(doc, action.Op);
            t.Start();
            SilentFailureHandler.Apply(t); // never block on a modal warning dialog (NFR-7)
            try
            {
                var res = handler!.Execute(doc, u, action, handles);
                t.Commit();

                // Verify the element actually survived (Revit silently removes
                // some invalid placements, e.g. a window too tall for its host).
                var el = doc.GetElement(res.Id);
                if (el == null)
                {
                    group.RollBack();
                    return Fail($"Action {i} ('{action.Op}') was rejected by Revit — the element did not survive " +
                                "(it may not fit its host or location). Nothing was committed.");
                }

                if (!string.IsNullOrEmpty(action.Handle)) handles[action.Handle!] = res.Id;
                createdIds.Add(res.Id);
                // Report the element's REAL category, not an assumed label.
                created.Add(new { handle = action.Handle, id = res.Id.Value, category = el.Category?.Name ?? res.Category });
            }
            catch (Exception ex)
            {
                if (t.GetStatus() == TransactionStatus.Started) t.RollBack();
                group.RollBack(); // atomic: discard the whole batch (FR-P6)
                return Fail($"Action {i} ('{action.Op}') failed: {ex.Message}");
            }
        }

        group.Assimilate(); // merge into a single undo step
        PlanRegistry.RecordCommit(doc, planId!, createdIds);
        PlanRegistry.ConsumePreview(doc, plan.Hash); // one preview authorises one commit

        audit["created"] = created;
        var audited = AuditLog.Append("plan.commit", "committed", audit);

        return RpcResponse.Success(request.Id, new
        {
            plan_id = planId,
            committed = true,
            created,
            audited,
        });
    }

    private static string Truncate(string s, int max) => s.Length <= max ? s : s[..max];
}
