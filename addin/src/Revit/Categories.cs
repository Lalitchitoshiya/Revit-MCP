using Autodesk.Revit.DB;

namespace RevitMCP.Addin.Revit;

/// <summary>Maps the wire's category strings to Revit BuiltInCategory.</summary>
public static class CategoryMap
{
    private static readonly Dictionary<string, BuiltInCategory> Map = new(StringComparer.OrdinalIgnoreCase)
    {
        ["walls"] = BuiltInCategory.OST_Walls,
        ["doors"] = BuiltInCategory.OST_Doors,
        ["windows"] = BuiltInCategory.OST_Windows,
        ["floors"] = BuiltInCategory.OST_Floors,
        ["rooms"] = BuiltInCategory.OST_Rooms,
        ["grids"] = BuiltInCategory.OST_Grids,
        ["levels"] = BuiltInCategory.OST_Levels,
        ["columns"] = BuiltInCategory.OST_Columns,
        ["structural_columns"] = BuiltInCategory.OST_StructuralColumns,
        ["ceilings"] = BuiltInCategory.OST_Ceilings,
        ["roofs"] = BuiltInCategory.OST_Roofs,
        ["furniture"] = BuiltInCategory.OST_Furniture,
    };

    /// <summary>Categories surfaced in model.summary counts.</summary>
    public static readonly string[] SummaryCategories =
        ["walls", "doors", "windows", "floors", "rooms", "grids", "levels"];

    public static bool TryResolve(string? name, out BuiltInCategory bic)
    {
        if (name != null && Map.TryGetValue(name, out bic)) return true;
        bic = BuiltInCategory.INVALID;
        return false;
    }
}
