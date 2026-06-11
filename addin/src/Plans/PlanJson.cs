using System.Text.Json;
using Autodesk.Revit.DB;
using RevitMCP.Addin.Revit;

namespace RevitMCP.Addin.Plans;

/// <summary>
/// Parses plan action parameters and resolves references against the live model
/// (docs/06 §6.1, §6.4). Lengths/points cross the wire in model units; this is
/// the single place they become internal feet (NFR-9).
/// </summary>
public static class PlanJson
{
    // Explicit unit -> feet factors, for the optional {value, unit} length form.
    private static readonly Dictionary<string, double> ToFeetFactor = new(StringComparer.OrdinalIgnoreCase)
    {
        ["mm"] = 1.0 / 304.8, ["millimeters"] = 1.0 / 304.8, ["millimeter"] = 1.0 / 304.8,
        ["cm"] = 1.0 / 30.48, ["centimeters"] = 1.0 / 30.48,
        ["m"] = 1.0 / 0.3048, ["meters"] = 1.0 / 0.3048, ["meter"] = 1.0 / 0.3048,
        ["ft"] = 1.0, ["feet"] = 1.0, ["foot"] = 1.0,
        ["in"] = 1.0 / 12.0, ["inches"] = 1.0 / 12.0, ["inch"] = 1.0 / 12.0,
    };

    /// <summary>A length value -> internal feet. Bare number = model units; an
    /// object {value, unit} = that explicit unit.</summary>
    public static bool TryLength(JsonElement p, string name, DocUnits u, bool required,
        out double feet, out Diagnostic? diag)
    {
        feet = 0;
        diag = null;
        if (p.ValueKind != JsonValueKind.Object || !p.TryGetProperty(name, out var v))
        {
            if (required) diag = Diagnostic.Error(DiagCodes.MissingField, $"Missing required field '{name}'.");
            return false;
        }
        return LengthToFeet(v, u, name, out feet, out diag);
    }

    private static bool LengthToFeet(JsonElement v, DocUnits u, string name, out double feet, out Diagnostic? diag)
    {
        feet = 0;
        diag = null;
        switch (v.ValueKind)
        {
            case JsonValueKind.Number:
                feet = u.ToFeet(v.GetDouble()); // model units
                return true;
            case JsonValueKind.Object:
                if (!v.TryGetProperty("value", out var val) || val.ValueKind != JsonValueKind.Number)
                {
                    diag = Diagnostic.Error(DiagCodes.MissingField, $"'{name}.value' missing or not a number.");
                    return false;
                }
                var unit = v.TryGetProperty("unit", out var un) ? un.GetString() : null;
                if (unit == null)
                {
                    diag = Diagnostic.Error(DiagCodes.UnitlessLength, $"'{name}' object has no 'unit'.");
                    return false;
                }
                if (!ToFeetFactor.TryGetValue(unit, out var f))
                {
                    diag = Diagnostic.Error(DiagCodes.UnitlessLength, $"Unknown unit '{unit}' on '{name}'.",
                        "Use mm, cm, m, ft, or in.");
                    return false;
                }
                feet = val.GetDouble() * f;
                return true;
            default:
                diag = Diagnostic.Error(DiagCodes.MissingField, $"'{name}' must be a number or {{value, unit}}.");
                return false;
        }
    }

    /// <summary>A 2D point [x, y] in model units -> XYZ in feet (Z = 0).</summary>
    public static bool TryPoint(JsonElement p, string name, DocUnits u, out XYZ ptFeet, out Diagnostic? diag)
    {
        ptFeet = XYZ.Zero;
        diag = null;
        if (p.ValueKind != JsonValueKind.Object || !p.TryGetProperty(name, out var arr) ||
            arr.ValueKind != JsonValueKind.Array || arr.GetArrayLength() < 2)
        {
            diag = Diagnostic.Error(DiagCodes.MissingField, $"'{name}' must be a [x, y] array.");
            return false;
        }
        var xy = arr.EnumerateArray().Take(2).ToArray();
        if (!LengthToFeet(xy[0], u, $"{name}.x", out var x, out diag)) return false;
        if (!LengthToFeet(xy[1], u, $"{name}.y", out var y, out diag)) return false;
        ptFeet = new XYZ(x, y, 0);
        return true;
    }

    /// <summary>Resolve a type reference (id, {id}, or {type_name, category}).</summary>
    public static bool TryResolveType(Document doc, JsonElement p, string name, BuiltInCategory category,
        out ElementId typeId, out Diagnostic? diag)
    {
        typeId = ElementId.InvalidElementId;
        diag = null;
        if (!p.TryGetProperty(name, out var r))
        {
            diag = Diagnostic.Error(DiagCodes.MissingField, $"Missing required field '{name}'.");
            return false;
        }

        if (TryGetId(r, out var idVal))
        {
            var el = doc.GetElement(ModelRead.ToElementId(idVal));
            if (el is ElementType)
            {
                typeId = el.Id;
                return true;
            }
            diag = Diagnostic.Error(DiagCodes.UnknownType, $"No type with id {idVal}.");
            return false;
        }

        var typeName = r.TryGetProperty("type_name", out var tn) ? tn.GetString() : null;
        if (typeName == null)
        {
            diag = Diagnostic.Error(DiagCodes.MissingField, $"'{name}' needs an id or type_name.");
            return false;
        }

        var matches = new FilteredElementCollector(doc)
            .OfCategory(category).WhereElementIsElementType().Cast<ElementType>()
            .Where(t => string.Equals(t.Name, typeName, StringComparison.OrdinalIgnoreCase))
            .ToList();

        if (matches.Count == 0)
        {
            diag = Diagnostic.Error(DiagCodes.UnknownType, $"No '{category}' type named '{typeName}'.",
                "Use list_types/search_families to find a valid type.");
            return false;
        }
        if (matches.Count > 1)
        {
            diag = Diagnostic.Error(DiagCodes.AmbiguousRef, $"'{typeName}' matches {matches.Count} types.",
                "Reference the type by id instead.");
            return false;
        }
        typeId = matches[0].Id;
        return true;
    }

    /// <summary>Resolve a level reference (id, {id}, or {level_name}).</summary>
    public static bool TryResolveLevel(Document doc, JsonElement p, string name,
        out Level? level, out Diagnostic? diag)
    {
        level = null;
        diag = null;
        if (!p.TryGetProperty(name, out var r))
        {
            diag = Diagnostic.Error(DiagCodes.MissingField, $"Missing required field '{name}'.");
            return false;
        }

        if (TryGetId(r, out var idVal))
        {
            if (doc.GetElement(ModelRead.ToElementId(idVal)) is Level lvl)
            {
                level = lvl;
                return true;
            }
            diag = Diagnostic.Error(DiagCodes.UnknownLevel, $"No level with id {idVal}.");
            return false;
        }

        var levelName = r.TryGetProperty("level_name", out var ln) ? ln.GetString() : null;
        if (levelName == null)
        {
            diag = Diagnostic.Error(DiagCodes.MissingField, $"'{name}' needs an id or level_name.");
            return false;
        }

        var levels = new FilteredElementCollector(doc).OfClass(typeof(Level)).Cast<Level>()
            .Where(l => string.Equals(l.Name, levelName, StringComparison.OrdinalIgnoreCase)).ToList();
        if (levels.Count == 0)
        {
            diag = Diagnostic.Error(DiagCodes.UnknownLevel, $"No level named '{levelName}'.",
                "Use list_levels to find a valid level.");
            return false;
        }
        if (levels.Count > 1)
        {
            diag = Diagnostic.Error(DiagCodes.AmbiguousRef, $"'{levelName}' matches {levels.Count} levels.");
            return false;
        }
        level = levels[0];
        return true;
    }

    private static bool TryGetId(JsonElement r, out long id)
    {
        id = 0;
        if (r.ValueKind == JsonValueKind.Number && r.TryGetInt64(out id)) return true;
        if (r.ValueKind == JsonValueKind.Object && r.TryGetProperty("id", out var idEl) && idEl.TryGetInt64(out id))
            return true;
        return false;
    }
}
