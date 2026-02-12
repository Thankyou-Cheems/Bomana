using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Runtime.CompilerServices;
using System.Text.Json;
using Bomana.WinUI3.Serialization;
using Microsoft.UI;
using Microsoft.UI.Dispatching;
using Microsoft.UI.Xaml.Media;

namespace Bomana.WinUI3.Views;

public sealed partial class MainPage : Page, INotifyPropertyChanged
{
    private readonly HttpClient _httpClient = new()
    {
        Timeout = TimeSpan.FromMilliseconds(900),
    };

    private readonly DispatcherQueueTimer _pollTimer;
    private readonly DispatcherQueueTimer _healthTimer;

    private bool _polling;
    private bool _healthChecking;
    private DateTimeOffset _lastUpdate = DateTimeOffset.MinValue;

    private readonly string _snapshotEndpoint;
    private readonly string _healthEndpoint;

    private string _activeSection = "overview";

    public event PropertyChangedEventHandler? PropertyChanged;

    public ObservableCollection<ZoneRowItem> ZoneItems { get; } = [];
    public ObservableCollection<AirfieldRowItem> EnemyAirfieldItems { get; } = [];

    private static Brush FallbackBadgeBackground =>
        new SolidColorBrush(ColorHelper.FromArgb(255, 47, 61, 89));

    private static Brush FallbackBadgeForeground =>
        new SolidColorBrush(ColorHelper.FromArgb(255, 242, 245, 249));

    private static Brush StatusInfoBrush =>
        new SolidColorBrush(ColorHelper.FromArgb(255, 31, 111, 235));

    private static Brush StatusSuccessBrush =>
        new SolidColorBrush(ColorHelper.FromArgb(255, 26, 142, 79));

    private static Brush StatusWarningBrush =>
        new SolidColorBrush(ColorHelper.FromArgb(255, 204, 122, 36));

    private static Brush StatusErrorBrush =>
        new SolidColorBrush(ColorHelper.FromArgb(255, 199, 68, 68));

    private string _connectionTitle = "正在连接 Bomana 后端";
    private string _connectionMessage = "等待本地快照桥接服务...";
    private InfoBarSeverity _connectionSeverity = InfoBarSeverity.Informational;
    private string _connectionPillText = "连接中";
    private Brush _connectionPillBackgroundBrush = StatusInfoBrush;
    private string _lastUpdatedText = "尚未收到快照";

    private string _remainingText = "--:--";
    private string _statusText = "初始化中";
    private string _mainBadgeText = "IDLE";
    private string _flightBadgeText = "—";
    private Brush _mainBadgeBackgroundBrush = FallbackBadgeBackground;
    private Brush _mainBadgeForegroundBrush = FallbackBadgeForeground;
    private Brush _flightBadgeBackgroundBrush = FallbackBadgeBackground;
    private Brush _flightBadgeForegroundBrush = FallbackBadgeForeground;
    private string _sortieText = "Sortie #--";
    private string _lifeCycleText = "Life -- · Cycle --";
    private double _progressPercent;

    private string _phaseText = "IDLE";
    private string _groundText = "未知";
    private string _headingText = "---°";
    private string _targetStateText = "无目标";

    private string _fuelText = "0 kg · 0%";
    private double _fuelPercentValue;
    private string _fuelEtaText = "预计剩余: --:--";

    private string _pitchText = "0.0°";
    private string _rollText = "0.0°";
    private string _attitudeStateText = "姿态链路：等待数据";

    private string _friendlyAirfieldText = "友方机场：暂无";
    private string _diagnosticsText = "";

    public MainPage()
    {
        InitializeComponent();
        DataContext = this;

        _snapshotEndpoint = ResolveEndpoint(
            directEnv: "BOMANA_SNAPSHOT_API_URL",
            path: "snapshot",
            defaultPort: 19081
        );
        _healthEndpoint = ResolveEndpoint(
            directEnv: "BOMANA_SNAPSHOT_HEALTH_URL",
            path: "health",
            defaultPort: 19081
        );

        _pollTimer = DispatcherQueue.GetForCurrentThread().CreateTimer();
        _pollTimer.Interval = TimeSpan.FromMilliseconds(100);
        _pollTimer.Tick += async (_, _) => await PollSnapshotAsync();

        _healthTimer = DispatcherQueue.GetForCurrentThread().CreateTimer();
        _healthTimer.Interval = TimeSpan.FromSeconds(2);
        _healthTimer.Tick += async (_, _) => await CheckHealthAsync();

        Loaded += OnLoaded;
        Unloaded += OnUnloaded;

        SetActiveSection("overview");
        UpdateConnectionPill(_connectionSeverity);

        OnPropertyChanged(nameof(SnapshotEndpointText));
        OnPropertyChanged(nameof(HealthEndpointText));
        OnPropertyChanged(nameof(ConnectionPillText));
        OnPropertyChanged(nameof(ConnectionPillBackgroundBrush));
    }

    public string SnapshotEndpointText => $"Snapshot Endpoint: {_snapshotEndpoint}";
    public string HealthEndpointText => $"Health Endpoint: {_healthEndpoint}";
    public string ConnectionTitle => _connectionTitle;
    public string ConnectionMessage => _connectionMessage;
    public InfoBarSeverity ConnectionSeverity => _connectionSeverity;
    public string ConnectionPillText => _connectionPillText;
    public Brush ConnectionPillBackgroundBrush => _connectionPillBackgroundBrush;
    public string LastUpdatedText => _lastUpdatedText;

    public string CurrentSectionTitle => _activeSection switch
    {
        "navigation" => "Fluent 导航视图",
        "system" => "系统与诊断",
        _ => "Bomana Fluent 仪表盘",
    };

    public string CurrentSectionSubtitle => _activeSection switch
    {
        "navigation" => "战区与机场路径在一个信息面板内联动更新。",
        "system" => "桥接、端点与稳定性保护策略集中查看。",
        _ => "实时快照驱动的飞行状态与燃油管理总览。",
    };

    public Visibility OverviewVisibility =>
        _activeSection == "overview" ? Visibility.Visible : Visibility.Collapsed;

    public Visibility NavigationVisibility =>
        _activeSection == "navigation" ? Visibility.Visible : Visibility.Collapsed;

    public Visibility SystemVisibility =>
        _activeSection == "system" ? Visibility.Visible : Visibility.Collapsed;

    public string RemainingText => _remainingText;
    public string StatusText => _statusText;
    public string MainBadgeText => _mainBadgeText;
    public string FlightBadgeText => _flightBadgeText;
    public Brush MainBadgeBackgroundBrush => _mainBadgeBackgroundBrush;
    public Brush MainBadgeForegroundBrush => _mainBadgeForegroundBrush;
    public Brush FlightBadgeBackgroundBrush => _flightBadgeBackgroundBrush;
    public Brush FlightBadgeForegroundBrush => _flightBadgeForegroundBrush;
    public string SortieText => _sortieText;
    public string LifeCycleText => _lifeCycleText;
    public double ProgressPercent => _progressPercent;

    public string PhaseText => _phaseText;
    public string GroundText => _groundText;
    public string HeadingText => _headingText;
    public string TargetStateText => _targetStateText;

    public string FuelText => _fuelText;
    public double FuelPercentValue => _fuelPercentValue;
    public string FuelEtaText => _fuelEtaText;

    public string PitchText => _pitchText;
    public string RollText => _rollText;
    public string AttitudeStateText => _attitudeStateText;

    public string FriendlyAirfieldText => _friendlyAirfieldText;
    public string DiagnosticsText => _diagnosticsText;

    private async void OnLoaded(object sender, RoutedEventArgs e)
    {
        if (ShellNavigation.SelectedItem is null && ShellNavigation.MenuItems.Count > 0)
        {
            if (ShellNavigation.MenuItems[0] is NavigationViewItem first)
            {
                ShellNavigation.SelectedItem = first;
            }
        }

        _pollTimer.Start();
        _healthTimer.Start();
        await CheckHealthAsync();
        await PollSnapshotAsync();
    }

    private void OnUnloaded(object sender, RoutedEventArgs e)
    {
        _pollTimer.Stop();
        _healthTimer.Stop();
    }

    private void OnShellNavigationSelectionChanged(
        NavigationView sender,
        NavigationViewSelectionChangedEventArgs args
    )
    {
        if (args.SelectedItemContainer?.Tag is string tag)
        {
            SetActiveSection(tag);
        }
    }

    private async void OnReconnectClick(object sender, RoutedEventArgs e)
    {
        await CheckHealthAsync(force: true);
        await PollSnapshotAsync(force: true);
    }

    private async Task PollSnapshotAsync(bool force = false)
    {
        if (_polling && !force)
        {
            return;
        }

        _polling = true;
        try
        {
            using var response = await _httpClient.GetAsync(_snapshotEndpoint);
            response.EnsureSuccessStatusCode();
            var json = await response.Content.ReadAsStringAsync();
            var snapshot = JsonSerializer.Deserialize(json, SnapshotJsonContext.Default.SnapshotDto);
            if (snapshot is null || !snapshot.Ok)
            {
                SetConnection(
                    title: "快照不可用",
                    message: "接口返回空数据或无效数据。",
                    severity: InfoBarSeverity.Warning
                );
                return;
            }

            ApplySnapshot(snapshot);
        }
        catch (Exception ex)
        {
            SetConnection(
                title: "快照轮询失败",
                message: ex.Message,
                severity: InfoBarSeverity.Error
            );
        }
        finally
        {
            _polling = false;
        }
    }

    private async Task CheckHealthAsync(bool force = false)
    {
        if (_healthChecking && !force)
        {
            return;
        }

        _healthChecking = true;
        try
        {
            using var response = await _httpClient.GetAsync(_healthEndpoint);
            response.EnsureSuccessStatusCode();
            var json = await response.Content.ReadAsStringAsync();
            var health = JsonSerializer.Deserialize(json, SnapshotJsonContext.Default.HealthDto);
            if (health is null || !health.Ok)
            {
                SetConnection(
                    title: "桥接服务异常",
                    message: "健康检查失败。",
                    severity: InfoBarSeverity.Warning
                );
                return;
            }
        }
        catch (Exception ex)
        {
            SetConnection(
                title: "桥接服务离线",
                message: ex.Message,
                severity: InfoBarSeverity.Error
            );
        }
        finally
        {
            _healthChecking = false;
        }
    }

    private void ApplySnapshot(SnapshotDto snapshot)
    {
        _lastUpdate = DateTimeOffset.Now;

        _remainingText = snapshot.Remaining_Text;
        _statusText = snapshot.Status_Text;
        _mainBadgeText = snapshot.Main_Badge?.Text ?? "—";
        _flightBadgeText = snapshot.Flight_Badge?.Text ?? "—";
        _mainBadgeBackgroundBrush = ParseBrush(snapshot.Main_Badge?.Bg, FallbackBadgeBackground);
        _mainBadgeForegroundBrush = ParseBrush(snapshot.Main_Badge?.Fg, FallbackBadgeForeground);
        _flightBadgeBackgroundBrush = ParseBrush(snapshot.Flight_Badge?.Bg, FallbackBadgeBackground);
        _flightBadgeForegroundBrush = ParseBrush(snapshot.Flight_Badge?.Fg, FallbackBadgeForeground);
        _sortieText = $"Sortie #{Math.Max(0, snapshot.Sortie_Id)}";
        _lifeCycleText = $"Life {snapshot.Life_Index?.ToString() ?? "--"} · Cycle {snapshot.Cycle?.ToString() ?? "--"}";
        _progressPercent = Math.Clamp(snapshot.Progress * 100.0, 0.0, 100.0);

        _phaseText = snapshot.Phase;
        _groundText = snapshot.On_Ground ? "地面/着陆" : "空中";
        _headingText = $"{snapshot.Player_Heading:0.0}°";
        _targetStateText = snapshot.Has_Target ? "战区目标已锁定" : "尚未锁定目标";

        _fuelPercentValue = Math.Clamp(snapshot.Fuel_Percent, 0.0, 100.0);
        _fuelText = $"{snapshot.Fuel_Kg:0.0} kg · {snapshot.Fuel_Percent:0.0}%";
        _fuelEtaText = string.IsNullOrWhiteSpace(snapshot.Fuel_Time_Remaining_Str)
            ? "预计剩余: --:--"
            : $"预计剩余: {snapshot.Fuel_Time_Remaining_Str}";

        _pitchText = $"{snapshot.Attitude_Pitch_Deg:+0.0;-0.0;0.0}°";
        _rollText = $"{snapshot.Attitude_Roll_Deg:+0.0;-0.0;0.0}°";
        _attitudeStateText = snapshot.Attitude_Reliable
            ? "姿态链路：可靠"
            : $"姿态链路：降级（{snapshot.Hud_Attitude_Fallback_Reason})";

        _friendlyAirfieldText = BuildFriendlyAirfieldText(snapshot.Friendly_Airfield);

        ZoneItems.Clear();
        foreach (var zone in snapshot.Zones ?? [])
        {
            ZoneItems.Add(new ZoneRowItem
            {
                Title = zone.Is_Target ? $"★ {zone.Id}" : zone.Id,
                Distance = $"{zone.Distance_Km:0.0} km",
                Bearing = $"{zone.Direction} {zone.Relative:+0;-0;0}°",
                Ete = string.IsNullOrWhiteSpace(zone.Ete_Str) ? "--:--" : zone.Ete_Str,
                Cdi = string.IsNullOrWhiteSpace(zone.Cdi_Indicator) ? "" : zone.Cdi_Indicator,
                IsTarget = zone.Is_Target,
            });
        }

        EnemyAirfieldItems.Clear();
        foreach (var airfield in snapshot.Enemy_Airfields ?? [])
        {
            EnemyAirfieldItems.Add(new AirfieldRowItem
            {
                Title = airfield.Id,
                Side = airfield.Side,
                Distance = $"{airfield.Distance_Km:0.0} km",
                Bearing = $"{airfield.Direction} {airfield.Relative:+0;-0;0}°",
                Ete = string.IsNullOrWhiteSpace(airfield.Ete_Str) ? "--:--" : airfield.Ete_Str,
            });
        }

        _diagnosticsText = BuildDiagnostics(snapshot);
        _lastUpdatedText = $"最近更新: {_lastUpdate:HH:mm:ss.fff}";

        if (snapshot.Api_Down)
        {
            SetConnection(
                title: "8111 连接断开",
                message: "后端正在重试，请检查游戏是否在战斗中且 8111 已启用。",
                severity: InfoBarSeverity.Error
            );
        }
        else if (snapshot.Api_Down_Pending)
        {
            SetConnection(
                title: "8111 状态抖动",
                message: "正在等待稳定数据，界面使用短时容错快照。",
                severity: InfoBarSeverity.Warning
            );
        }
        else
        {
            SetConnection(
                title: "数据链路正常",
                message: "WinUI3 Fluent 仪表盘正在实时渲染。",
                severity: InfoBarSeverity.Success
            );
        }

        NotifyAll();
    }

    private static string BuildFriendlyAirfieldText(AirfieldDto? airfield)
    {
        if (airfield is null)
        {
            return "友方机场：暂无";
        }

        var ete = string.IsNullOrWhiteSpace(airfield.Ete_Str) ? "--:--" : airfield.Ete_Str;
        return $"友方机场 {airfield.Id} · {airfield.Distance_Km:0.0} km · {airfield.Direction} {airfield.Relative:+0;-0;0}° · ETE {ete}";
    }

    private string BuildDiagnostics(SnapshotDto snapshot)
    {
        return
            $"Phase={snapshot.Phase}  Sortie={snapshot.Sortie_Id}  Heading={snapshot.Player_Heading:0.0}\n" +
            $"Target={snapshot.Has_Target}  AirfieldTarget={snapshot.Has_Airfield_Target}  Ground={snapshot.On_Ground}\n" +
            $"AttitudeReliable={snapshot.Attitude_Reliable}  Fallback={snapshot.Hud_Attitude_Fallback} ({snapshot.Hud_Attitude_Fallback_Reason})\n" +
            $"SnapshotTS={snapshot.Ts:0.000}  Schema={snapshot.Schema_Version}  Version={snapshot.Version}\n\n" +
            snapshot.Diag_Text;
    }

    private void SetConnection(string title, string message, InfoBarSeverity severity)
    {
        _connectionTitle = title;
        _connectionMessage = message;
        _connectionSeverity = severity;
        UpdateConnectionPill(severity);

        OnPropertyChanged(nameof(ConnectionTitle));
        OnPropertyChanged(nameof(ConnectionMessage));
        OnPropertyChanged(nameof(ConnectionSeverity));
        OnPropertyChanged(nameof(ConnectionPillText));
        OnPropertyChanged(nameof(ConnectionPillBackgroundBrush));
    }

    private void SetActiveSection(string tag)
    {
        var normalized = tag.Trim().ToLowerInvariant();
        if (normalized != "overview" && normalized != "navigation" && normalized != "system")
        {
            normalized = "overview";
        }

        if (_activeSection == normalized)
        {
            return;
        }

        _activeSection = normalized;
        OnPropertyChanged(nameof(CurrentSectionTitle));
        OnPropertyChanged(nameof(CurrentSectionSubtitle));
        OnPropertyChanged(nameof(OverviewVisibility));
        OnPropertyChanged(nameof(NavigationVisibility));
        OnPropertyChanged(nameof(SystemVisibility));
    }

    private void UpdateConnectionPill(InfoBarSeverity severity)
    {
        switch (severity)
        {
            case InfoBarSeverity.Success:
                _connectionPillText = "已连接";
                _connectionPillBackgroundBrush = StatusSuccessBrush;
                break;
            case InfoBarSeverity.Warning:
                _connectionPillText = "波动";
                _connectionPillBackgroundBrush = StatusWarningBrush;
                break;
            case InfoBarSeverity.Error:
                _connectionPillText = "离线";
                _connectionPillBackgroundBrush = StatusErrorBrush;
                break;
            default:
                _connectionPillText = "连接中";
                _connectionPillBackgroundBrush = StatusInfoBrush;
                break;
        }
    }

    private void NotifyAll()
    {
        OnPropertyChanged(nameof(LastUpdatedText));
        OnPropertyChanged(nameof(RemainingText));
        OnPropertyChanged(nameof(StatusText));
        OnPropertyChanged(nameof(MainBadgeText));
        OnPropertyChanged(nameof(FlightBadgeText));
        OnPropertyChanged(nameof(MainBadgeBackgroundBrush));
        OnPropertyChanged(nameof(MainBadgeForegroundBrush));
        OnPropertyChanged(nameof(FlightBadgeBackgroundBrush));
        OnPropertyChanged(nameof(FlightBadgeForegroundBrush));
        OnPropertyChanged(nameof(SortieText));
        OnPropertyChanged(nameof(LifeCycleText));
        OnPropertyChanged(nameof(ProgressPercent));
        OnPropertyChanged(nameof(PhaseText));
        OnPropertyChanged(nameof(GroundText));
        OnPropertyChanged(nameof(HeadingText));
        OnPropertyChanged(nameof(TargetStateText));
        OnPropertyChanged(nameof(FuelText));
        OnPropertyChanged(nameof(FuelPercentValue));
        OnPropertyChanged(nameof(FuelEtaText));
        OnPropertyChanged(nameof(PitchText));
        OnPropertyChanged(nameof(RollText));
        OnPropertyChanged(nameof(AttitudeStateText));
        OnPropertyChanged(nameof(FriendlyAirfieldText));
        OnPropertyChanged(nameof(DiagnosticsText));
    }

    private static string ResolveEndpoint(string directEnv, string path, int defaultPort)
    {
        var direct = (Environment.GetEnvironmentVariable(directEnv) ?? "").Trim();
        if (!string.IsNullOrWhiteSpace(direct))
        {
            return direct;
        }

        var host = (Environment.GetEnvironmentVariable("BOMANA_UI_BRIDGE_HOST") ?? "127.0.0.1").Trim();
        var portText = (Environment.GetEnvironmentVariable("BOMANA_UI_BRIDGE_PORT") ?? "").Trim();
        if (!int.TryParse(portText, out var port) || port <= 0 || port > 65535)
        {
            port = defaultPort;
        }

        return $"http://{host}:{port}/{path}";
    }

    private static Brush ParseBrush(string? colorText, Brush fallback)
    {
        if (string.IsNullOrWhiteSpace(colorText))
        {
            return fallback;
        }

        var s = colorText.Trim();
        if (!s.StartsWith("#", StringComparison.Ordinal))
        {
            return fallback;
        }

        try
        {
            if (s.Length == 7)
            {
                var r = Convert.ToByte(s.Substring(1, 2), 16);
                var g = Convert.ToByte(s.Substring(3, 2), 16);
                var b = Convert.ToByte(s.Substring(5, 2), 16);
                return new SolidColorBrush(ColorHelper.FromArgb(255, r, g, b));
            }

            if (s.Length == 9)
            {
                var a = Convert.ToByte(s.Substring(1, 2), 16);
                var r = Convert.ToByte(s.Substring(3, 2), 16);
                var g = Convert.ToByte(s.Substring(5, 2), 16);
                var b = Convert.ToByte(s.Substring(7, 2), 16);
                return new SolidColorBrush(ColorHelper.FromArgb(a, r, g, b));
            }
        }
        catch
        {
            return fallback;
        }

        return fallback;
    }

    private void OnPropertyChanged([CallerMemberName] string? name = null)
    {
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
    }
}
