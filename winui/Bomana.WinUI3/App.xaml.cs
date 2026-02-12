using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Navigation;
using Windows.Graphics;

namespace Bomana.WinUI3;

public partial class App : Application
{
    private Window? _window;

    public App()
    {
        InitializeComponent();
    }

    protected override void OnLaunched(LaunchActivatedEventArgs args)
    {
        _window ??= new Window();

        if (_window.Content is not Frame rootFrame)
        {
            rootFrame = new Frame();
            rootFrame.NavigationFailed += OnNavigationFailed;
            _window.Content = rootFrame;
        }

        _ = rootFrame.Navigate(typeof(MainPage), args.Arguments);
        _window.Title = "Bomana WinUI3";
        _window.SystemBackdrop = new MicaBackdrop();

        // Reasonable desktop baseline size for HUD-control + nav workflows.
        if (_window.AppWindow is AppWindow appWindow)
        {
            appWindow.Resize(new SizeInt32(1320, 860));
        }

        _window.Activate();
    }

    private static void OnNavigationFailed(object sender, NavigationFailedEventArgs e)
    {
        throw new InvalidOperationException($"Failed to load page {e.SourcePageType.FullName}");
    }
}
