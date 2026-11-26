using Autodesk.Revit.DB;

namespace RevitMCP.Addin.Plans;

/// <summary>
/// Session-scoped commit bookkeeping (docs/03 §3.3). Only touched on the Revit
/// UI thread (command execution is serialized there), so no locking is needed.
///
/// - Previewed plan hashes gate commits: a plan must be previewed IN THE SAME
///   DOCUMENT before it can be committed, the committed plan must match the
///   previewed one, and a preview is consumed by its commit (no replay).
/// - Committed element ids per plan (with their document) enable a targeted
///   undo that refuses to run against a different document.
/// </summary>
public static class PlanRegistry
{
    private static readonly HashSet<string> PreviewedKeys = new(StringComparer.Ordinal);
    private static readonly Dictionary<string, (string DocKey, List<ElementId> Ids)> CommittedByPlan = new();
    private static string? _lastCommittedPlanId;

    /// <summary>Stable identity of a document within this Revit session.</summary>
    public static string DocKey(Document doc) =>
        string.IsNullOrEmpty(doc.PathName) ? "unsaved:" + doc.Title : doc.PathName;

    private static string Key(Document doc, string hash) => DocKey(doc) + "|" + hash;

    public static void MarkPreviewed(Document doc, string hash) => PreviewedKeys.Add(Key(doc, hash));

    public static bool IsPreviewed(Document doc, string hash) => PreviewedKeys.Contains(Key(doc, hash));

    /// <summary>A preview authorises exactly one commit.</summary>
    public static void ConsumePreview(Document doc, string hash) => PreviewedKeys.Remove(Key(doc, hash));

    public static void RecordCommit(Document doc, string planId, List<ElementId> created)
    {
        CommittedByPlan[planId] = (DocKey(doc), created);
        _lastCommittedPlanId = planId;
    }

    public static bool TryGetCommitted(string planId, out string docKey, out List<ElementId> created)
    {
        if (CommittedByPlan.TryGetValue(planId, out var entry))
        {
            docKey = entry.DocKey;
            created = entry.Ids;
            return true;
        }
        docKey = "";
        created = null!;
        return false;
    }

    public static void RemoveCommitted(string planId)
    {
        CommittedByPlan.Remove(planId);
        if (_lastCommittedPlanId == planId) _lastCommittedPlanId = null;
    }

    public static string? LastCommittedPlanId => _lastCommittedPlanId;
}
