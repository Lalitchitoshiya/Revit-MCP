using RevitMCP.Addin.Protocol;

namespace RevitMCP.Addin.Commands;

/// <summary>Maps wire method names to command handlers.</summary>
public sealed class CommandRegistry
{
    private readonly Dictionary<string, ICommand> _commands = new(StringComparer.Ordinal);

    public CommandRegistry Register(ICommand command)
    {
        _commands[command.Method] = command;
        return this;
    }

    public bool TryGet(string? method, out ICommand command)
    {
        command = null!;
        return method != null && _commands.TryGetValue(method, out command!);
    }

    /// <summary>Registry: Phase 0 health check + Phase 1 read-only discovery (docs/07).</summary>
    public static CommandRegistry CreateDefault() =>
        new CommandRegistry()
            .Register(new HealthCheckCommand())
            .Register(new ModelSummaryCommand())
            .Register(new LevelsListCommand())
            .Register(new GridsListCommand())
            .Register(new TypesListCommand())
            .Register(new FamiliesSearchCommand())
            .Register(new ElementsQueryCommand())
            .Register(new ContextGetCommand());
}
