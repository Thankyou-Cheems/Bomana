package main

import (
	"net/url"
	"strings"
	"testing"
)

func TestTrayUsesOnlyFixedBomanaHTTPSDestinations(t *testing.T) {
	config := defaultTrayConfig("http://127.0.0.1:8878/mobile-pairing", func() {})
	for name, raw := range map[string]string{"Launcher": config.launcherURL, "Web": config.webURL, "Sponsor": config.sponsorURL} {
		parsed, err := url.Parse(raw)
		if err != nil || parsed.Scheme != "https" || parsed.Host != "bomana.ruikang.wang" || parsed.RawQuery != "" || parsed.Fragment != "" {
			t.Fatalf("%s tray destination is not a fixed Bomana HTTPS URL: %q", name, raw)
		}
	}
	if config.launcherURL != "https://bomana.ruikang.wang/launcher/" {
		t.Fatalf("unexpected Launcher URL: %q", config.launcherURL)
	}
	if config.webURL != "https://bomana.ruikang.wang/app/Enhanced/" {
		t.Fatalf("unexpected Web URL: %q", config.webURL)
	}
	if config.mobilePairingURL != "http://127.0.0.1:8878/mobile-pairing" {
		t.Fatalf("unexpected mobile pairing URL: %q", config.mobilePairingURL)
	}
	if config.projectURL != "https://github.com/Thankyou-Cheems/Bomana" {
		t.Fatalf("unexpected project URL: %q", config.projectURL)
	}
	if config.sponsorURL != "https://bomana.ruikang.wang/downloads/sponsor_wechat.png" {
		t.Fatalf("unexpected sponsor URL: %q", config.sponsorURL)
	}
	if config.enhancedSupportURL != "https://bomana.ruikang.wang/launcher/?intent=Enhanced" {
		t.Fatalf("unexpected Enhanced support URL: %q", config.enhancedSupportURL)
	}
	if config.privacyURL != "https://github.com/Thankyou-Cheems/Bomana/blob/main/docs/PRIVACY.md" {
		t.Fatalf("unexpected privacy URL: %q", config.privacyURL)
	}
}

func TestTrayActionsOpenOnlyFixedDestinationsAndExit(t *testing.T) {
	exits := 0
	opened := make([]string, 0, 4)
	details := make([]trayAboutDetails, 0, 1)
	config := defaultTrayConfig("http://127.0.0.1:8878/mobile-pairing", func() { exits++ })
	opener := func(raw string) { opened = append(opened, raw) }
	showDetails := func(value trayAboutDetails) { details = append(details, value) }
	performTrayAction(config, trayActionOpenWeb, opener, showDetails)
	performTrayAction(config, trayActionMobilePairing, opener, showDetails)
	performTrayAction(config, trayActionOpenLauncher, opener, showDetails)
	performTrayAction(config, trayActionStarProject, opener, showDetails)
	performTrayAction(config, trayActionSponsor, opener, showDetails)
	performTrayAction(config, trayActionAbout, opener, showDetails)
	performTrayAction(config, trayActionExit, opener, showDetails)
	if len(opened) != 5 || opened[0] != webURL || opened[1] != config.mobilePairingURL || opened[2] != launcherURL || opened[3] != projectURL || opened[4] != sponsorURL {
		t.Fatalf("unexpected tray destinations: %#v", opened)
	}
	if exits != 1 {
		t.Fatalf("exit requests = %d, want 1", exits)
	}
	if len(details) != 1 || details[0] != buildTrayAbout(config) {
		t.Fatalf("version details = %#v", details)
	}
}

func TestTrayAboutRestoresAuthorSponsorAndBuildDetails(t *testing.T) {
	config := trayConfig{
		launcherURL:        launcherURL,
		webURL:             webURL,
		projectURL:         projectURL,
		sponsorURL:         sponsorURL,
		enhancedSupportURL: enhancedSupportURL,
		privacyURL:         privacyURL,
		bridgeVersion:      "1.2.8",
		appWebVersion:      "1.2.8",
		buildProvenance:    "github-actions-sigstore",
	}
	details := buildTrayAbout(config)
	allText := strings.Join([]string{details.windowTitle, details.mainInstruction, details.contentHTML, details.expandedHTML, details.footerHTML, formatTrayAboutPlain(details)}, "\n")
	for _, expected := range []string{"作者：Thankyou-Cheems", "MIT License", "支持作者", "订阅超级爆弹版", "微信赞赏码", "Ctrl+C", enhancedSupportURL, projectURL, sponsorURL, privacyURL, "Bridge：1.2.8", "App Web：1.2.8", "缓存协议：v4", "手机配对协议：v6", "GitHub Actions · Sigstore", "不读取游戏进程、内存、模块或输入"} {
		if !strings.Contains(allText, expected) {
			t.Fatalf("About details missing %q: %s", expected, allText)
		}
	}
	if strings.Contains(allText, "辅助") {
		t.Fatalf("About copy contains retired wording: %s", allText)
	}
	for _, allowed := range []string{enhancedSupportURL, sponsorURL, projectURL, privacyURL} {
		if !isAllowedTrayHyperlink(allowed) {
			t.Fatalf("fixed About hyperlink was rejected: %s", allowed)
		}
	}
	if isAllowedTrayHyperlink("https://example.invalid/") {
		t.Fatal("unexpected About hyperlink was allowed")
	}
}
