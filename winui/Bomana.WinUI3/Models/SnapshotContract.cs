namespace Bomana.WinUI3.Models;

public sealed class BadgeDto
{
    public string Text { get; set; } = "";
    public string Fg { get; set; } = "";
    public string Bg { get; set; } = "";
}

public sealed class ZoneDto
{
    public string Id { get; set; } = "";
    public double Distance_Km { get; set; }
    public string Direction { get; set; } = "";
    public double Relative { get; set; }
    public bool Is_Target { get; set; }
    public string Ete_Str { get; set; } = "";
    public string Cdi_Indicator { get; set; } = "";
    public string Cdi_Color { get; set; } = "";
}

public sealed class AirfieldDto
{
    public string Id { get; set; } = "";
    public string Side { get; set; } = "";
    public double Distance_Km { get; set; }
    public string Direction { get; set; } = "";
    public double Relative { get; set; }
    public bool Is_Target { get; set; }
    public string Ete_Str { get; set; } = "";
    public string Cdi_Indicator { get; set; } = "";
    public string Cdi_Color { get; set; } = "";
}

public sealed class SnapshotDto
{
    public bool Ok { get; set; }
    public int Schema_Version { get; set; }
    public string Version { get; set; } = "";
    public double Ts { get; set; }
    public string Phase { get; set; } = "IDLE";
    public int Sortie_Id { get; set; }
    public int? Life_Index { get; set; }
    public int? Cycle { get; set; }
    public double? Remaining_Sec { get; set; }
    public string Remaining_Text { get; set; } = "--:--";
    public double Progress { get; set; }
    public string Status_Text { get; set; } = "";
    public BadgeDto Main_Badge { get; set; } = new();
    public BadgeDto Flight_Badge { get; set; } = new();
    public bool Api_Down { get; set; }
    public bool Api_Down_Pending { get; set; }
    public bool On_Ground { get; set; }
    public bool Landed_Flash { get; set; }
    public double Player_Heading { get; set; }
    public List<ZoneDto> Zones { get; set; } = [];
    public ZoneDto? Target_Zone { get; set; }
    public AirfieldDto? Friendly_Airfield { get; set; }
    public List<AirfieldDto> Enemy_Airfields { get; set; } = [];
    public bool Has_Target { get; set; }
    public bool Has_Airfield_Target { get; set; }
    public double Fuel_Kg { get; set; }
    public double Fuel_Percent { get; set; }
    public string Fuel_Time_Remaining_Str { get; set; } = "";
    public double Attitude_Pitch_Deg { get; set; }
    public double Attitude_Roll_Deg { get; set; }
    public bool Attitude_Reliable { get; set; }
    public bool Hud_Attitude_Fallback { get; set; }
    public string Hud_Attitude_Fallback_Reason { get; set; } = "";
    public string Diag_Text { get; set; } = "";
}

public sealed class HealthDto
{
    public bool Ok { get; set; }
    public string Service { get; set; } = "";
    public string Version { get; set; } = "";
    public int Schema_Version { get; set; }
    public double Uptime_Sec { get; set; }
    public double Last_Snapshot_At { get; set; }
    public bool Api_Down { get; set; }
    public string Last_Error { get; set; } = "";
}

public sealed class ZoneRowItem
{
    public string Title { get; set; } = "";
    public string Distance { get; set; } = "";
    public string Bearing { get; set; } = "";
    public string Ete { get; set; } = "";
    public string Cdi { get; set; } = "";
    public bool IsTarget { get; set; }
}

public sealed class AirfieldRowItem
{
    public string Title { get; set; } = "";
    public string Distance { get; set; } = "";
    public string Bearing { get; set; } = "";
    public string Ete { get; set; } = "";
    public string Side { get; set; } = "";
}
