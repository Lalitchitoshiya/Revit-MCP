using Autodesk.Revit.DB;

namespace RevitMCP.Addin.Plans;

/// <summary>
/// Session-scoped commit bookkeeping (docs/03 §3.3). Only touched on the Revit
/// UI thread (command execution is serialized there), so no locking is needed.
///
/// - Previewed plan hashes gate commits: a plan must be previewed before it can
///   be committed, and the committed plan must match the previewed one.
/// - Committed element ids per plan enable a targeted undo.
/// </summary>
public static class PlanRegistry
{
    private static readonly HashSet<string> PreviewedHashes = new();
    private static readonly Dictionary<string, List<ElementId>> CommittedByPlan = new();
    private static string? _lastCommittedPlanId;

    public static void MarkPreviewed(string hash) => PreviewedHashes.Add(hash);

    public static bool IsPreviewed(string hash) => PreviewedHashes.Contains(hash);

    public static void RecordCommit(string planId, List<ElementId> created)
    {
        CommittedByPlan[planId] = created;
        _lastCommittedPlanId = planId;
    }

    public static bool TryGetCommitted(string planId, out List<ElementId> created) =>
        CommittedByPlan.TryGetValue(planId, out created!);

    public static void RemoveCommitted(string planId)
    {
        CommittedByPlan.Remove(planId);
        if (_lastCommittedPlanId == planId) _lastCommittedPlanId = null;
    }

    public static string? LastCommittedPlanId => _lastCommittedPlanId;
}
