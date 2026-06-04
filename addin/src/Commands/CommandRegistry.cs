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

    /// <summary>Phase 0 registry: just the health check (docs/07 Phase 0).</summary>
    public static CommandRegistry CreateDefault() =>
        new CommandRegistry().Register(new HealthCheckCommand());
}
