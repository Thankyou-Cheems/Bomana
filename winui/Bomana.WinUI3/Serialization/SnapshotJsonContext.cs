using System.Text.Json.Serialization;

namespace Bomana.WinUI3.Serialization;

[JsonSerializable(typeof(SnapshotDto))]
[JsonSerializable(typeof(HealthDto))]
internal partial class SnapshotJsonContext : JsonSerializerContext
{
}
