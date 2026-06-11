using Autodesk.Revit.DB;

namespace RevitMCP.Addin.Plans;

/// <summary>
/// Keeps commits non-interactive (NFR-1/NFR-7): Revit normally pops a MODAL
/// warning dialog during a transaction (e.g. "elements overlap", "room not
/// enclosed"), which would block our background socket thread forever. This
/// preprocessor deletes warnings so no dialog appears; genuine errors are left
/// to fail the transaction (which the commit then rolls back atomically).
/// </summary>
public sealed class SilentFailureHandler : IFailuresPreprocessor
{
    public FailureProcessingResult PreprocessFailures(FailuresAccessor accessor)
    {
        foreach (var failure in accessor.GetFailureMessages())
        {
            if (failure.GetSeverity() == FailureSeverity.Warning)
                accessor.DeleteWarning(failure);
        }
        return FailureProcessingResult.Continue;
    }

    /// <summary>Apply to a transaction so warnings are swallowed and no modal UI shows.</summary>
    public static void Apply(Transaction t)
    {
        var opts = t.GetFailureHandlingOptions();
        opts.SetForcedModalHandling(false);
        opts.SetClearAfterRollback(true);
        opts.SetFailuresPreprocessor(new SilentFailureHandler());
        t.SetFailureHandlingOptions(opts);
    }
}
