package main

import (
	"fmt"
	"strings"
)

const (
	launcherURL        = "https://bomana.ruikang.wang/launcher/"
	webURL             = "https://bomana.ruikang.wang/app/Enhanced/"
	projectURL         = "https://github.com/Thankyou-Cheems/Bomana"
	sponsorURL         = "https://bomana.ruikang.wang/downloads/sponsor_wechat.png"
	enhancedSupportURL = "https://bomana.ruikang.wang/launcher/?intent=Enhanced"
	privacyURL         = "https://github.com/Thankyou-Cheems/Bomana/blob/main/docs/PRIVACY.md"
)

type trayConfig struct {
	launcherURL        string
	webURL             string
	mobilePairingURL   string
	projectURL         string
	sponsorURL         string
	enhancedSupportURL string
	privacyURL         string
	bridgeVersion      string
	appWebVersion      string
	buildProvenance    string
	requestExit        func()
}

type trayAction uint8

type trayAboutDetails struct {
	windowTitle          string
	mainInstruction      string
	contentHTML          string
	expandedHTML         string
	expandedControlText  string
	collapsedControlText string
	footerHTML           string
}

const (
	trayActionOpenWeb trayAction = iota + 1
	trayActionMobilePairing
	trayActionOpenLauncher
	trayActionStarProject
	trayActionSponsor
	trayActionAbout
	trayActionExit
)

func defaultTrayConfig(mobilePairingURL string, requestExit func()) trayConfig {
	return trayConfig{
		launcherURL:        launcherURL,
		webURL:             webURL,
		mobilePairingURL:   mobilePairingURL,
		projectURL:         projectURL,
		sponsorURL:         sponsorURL,
		enhancedSupportURL: enhancedSupportURL,
		privacyURL:         privacyURL,
		bridgeVersion:      bridgeVersion,
		appWebVersion:      appWebVersion,
		buildProvenance:    bridgeProvenance,
		requestExit:        requestExit,
	}
}

func performTrayAction(
	config trayConfig,
	action trayAction,
	openURL func(string),
	showAbout func(trayAboutDetails),
) {
	switch action {
	case trayActionOpenWeb:
		openURL(config.webURL)
	case trayActionMobilePairing:
		openURL(config.mobilePairingURL)
	case trayActionOpenLauncher:
		openURL(config.launcherURL)
	case trayActionStarProject:
		openURL(config.projectURL)
	case trayActionSponsor:
		openURL(config.sponsorURL)
	case trayActionAbout:
		if showAbout != nil {
			showAbout(buildTrayAbout(config))
		}
	case trayActionExit:
		if config.requestExit != nil {
			config.requestExit()
		}
	}
}

func buildTrayAbout(config trayConfig) trayAboutDetails {
	provenance := "本地未证明构建"
	if config.buildProvenance == "github-actions-sigstore" {
		provenance = "GitHub Actions · Sigstore"
	}
	return trayAboutDetails{
		windowTitle:     "关于 Bomana · 支持作者",
		mainInstruction: fmt.Sprintf("Bomana Bridge %s", config.bridgeVersion),
		contentHTML: fmt.Sprintf(
			"Bomana 是 Thankyou-Cheems 持续维护的战雷全真模式飞行工具。\n\n"+
				"支持作者\n优先选择 <A HREF=\"%s\">订阅超级爆弹版</A>，既可获得完整功能，也能支持长期维护。\n"+
				"如需额外支持，也可以打开 <A HREF=\"%s\">微信赞赏码</A>。\n\n"+
				"项目与隐私\n<A HREF=\"%s\">给项目点个 Star / 查看源码</A>　·　<A HREF=\"%s\">隐私政策</A>\n\n"+
				"按 Ctrl+C 可复制本窗口全部内容。",
			config.enhancedSupportURL,
			config.sponsorURL,
			config.projectURL,
			config.privacyURL,
		),
		expandedHTML: fmt.Sprintf(
			"运行边界\n"+
				"• Bridge 仅连接官方 localhost:8111，并管理签名地形缓存。\n"+
				"• 飞行状态、导航与武器解算在用户浏览器本地执行。\n"+
				"• 不读取游戏进程、内存、模块或输入。\n\n"+
				"版本与构建\nBridge：%s\nApp Web：%s\nBridge 协议：v1\n缓存协议：v4\n手机配对协议：v6\n构建来源：%s",
			config.bridgeVersion,
			config.appWebVersion,
			provenance,
		),
		expandedControlText:  "查看版本与运行边界",
		collapsedControlText: "收起版本与运行边界",
		footerHTML: fmt.Sprintf(
			"作者：Thankyou-Cheems　·　MIT License　·　<A HREF=\"%s\">Bomana 项目主页</A>\n"+
				"War Thunder 商标归 Gaijin Entertainment 所有；Bomana 为独立项目。",
			config.projectURL,
		),
	}
}

func formatTrayAboutPlain(details trayAboutDetails) string {
	replacer := strings.NewReplacer(
		"<b>", "", "</b>", "",
		"<A HREF=\"", "", "\">", "：", "</A>", "",
		"<a href=\"", "", "\">", "：", "</a>", "",
	)
	return fmt.Sprintf("%s\n\n%s\n\n%s\n\n%s", details.mainInstruction, replacer.Replace(details.contentHTML), replacer.Replace(details.expandedHTML), replacer.Replace(details.footerHTML))
}

func isAllowedTrayHyperlink(raw string) bool {
	return raw == enhancedSupportURL || raw == sponsorURL || raw == projectURL || raw == privacyURL
}
