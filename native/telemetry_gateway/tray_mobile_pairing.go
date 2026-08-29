package main

import (
	"encoding/base64"
	"fmt"
	"html"
	"net/http"
	"net/url"
	"strconv"
	"time"

	qrcode "github.com/skip2/go-qrcode"
)

func (gateway *relay) serveTrayMobilePairing(response http.ResponseWriter, request *http.Request) {
	if request.RemoteAddr != "" && !isLoopbackRemote(request.RemoteAddr) {
		http.Error(response, "loopback required", http.StatusForbidden)
		return
	}
	if request.Method == http.MethodPost {
		if request.URL.RawQuery != "rotate=1" || !sameOriginTrayPairingRequest(request) {
			http.Error(response, "origin forbidden", http.StatusForbidden)
			return
		}
		if _, err := gateway.mobile.Start(gateway, time.Now(), true); err != nil {
			http.Error(response, "mobile pairing unavailable", http.StatusServiceUnavailable)
			return
		}
		response.Header().Set("Cache-Control", "no-store")
		response.Header().Set("Location", "/mobile-pairing")
		response.WriteHeader(http.StatusSeeOther)
		return
	}
	if request.Method != http.MethodGet && request.Method != http.MethodHead {
		response.Header().Set("Allow", "GET, HEAD, POST")
		http.Error(response, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	now := time.Now()
	if descriptor, claimed, ok := gateway.mobile.Current(now); ok && claimed {
		writeTrayPairingPage(response, trayPairingPage{
			Title:      "手机已连接",
			Message:    "当前手机会话仍然有效。关闭电脑网页不会中断手机；请保持 Bridge 运行。",
			ExpiresAt:  descriptor.ExpiresAt,
			Regenerate: true,
		}, request.Method == http.MethodHead)
		return
	}
	descriptor, err := gateway.mobile.Start(gateway, now)
	if err != nil {
		http.Error(response, "mobile pairing unavailable", http.StatusServiceUnavailable)
		return
	}
	selected := selectedPairingNetwork(request, descriptor.Networks)
	pairingURL := trayPairingHandoffURL(descriptor, selected)
	png, err := qrcode.Encode(pairingURL, qrcode.Medium, 300)
	if err != nil {
		http.Error(response, "QR generation failed", http.StatusInternalServerError)
		return
	}
	writeTrayPairingPage(response, trayPairingPage{
		Title:      "连接手机",
		Message:    "用手机系统相机扫描二维码。通过 Web 配对时手机无需登录；从这里配对时，手机若尚未授权会在手机上登录 CheemsPay。",
		ExpiresAt:  descriptor.PairingExpiresAt,
		QRCodeData: "data:image/png;base64," + base64.StdEncoding.EncodeToString(png),
		Networks:   descriptor.Networks,
		Selected:   selected,
		Regenerate: true,
	}, request.Method == http.MethodHead)
}

type trayPairingPage struct {
	Title      string
	Message    string
	ExpiresAt  string
	QRCodeData string
	Networks   []mobileNetworkCandidate
	Selected   int
	Regenerate bool
}

func writeTrayPairingPage(response http.ResponseWriter, page trayPairingPage, head bool) {
	response.Header().Set("Cache-Control", "no-store")
	response.Header().Set("Content-Security-Policy", "default-src 'none'; img-src data:; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
	response.Header().Set("Referrer-Policy", "no-referrer")
	response.Header().Set("X-Content-Type-Options", "nosniff")
	response.Header().Set("Content-Type", "text/html; charset=utf-8")
	response.WriteHeader(http.StatusOK)
	if head {
		return
	}
	var networkLinks string
	for index, candidate := range page.Networks {
		className := ""
		if index == page.Selected {
			className = ` class="selected"`
		}
		networkLinks += fmt.Sprintf(`<a%s href="/mobile-pairing?network=%d">%s · %s</a>`, className, index, html.EscapeString(candidate.Interface), html.EscapeString(candidate.Address))
	}
	qr := ""
	if page.QRCodeData != "" {
		qr = `<img src="` + html.EscapeString(page.QRCodeData) + `" alt="Bomana 手机配对二维码" width="300" height="300">`
	}
	regenerate := ""
	if page.Regenerate {
		regenerate = `<form method="post" action="/mobile-pairing?rotate=1"><button class="regenerate" type="submit">重新生成并撤销旧会话</button></form>`
	}
	body := `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>` + html.EscapeString(page.Title) + ` · Bomana Bridge</title><style>` + trayPairingCSS + `</style></head><body><main><header><b>B</b><div><small>BOMANA BRIDGE</small><h1>` + html.EscapeString(page.Title) + `</h1></div></header><p>` + html.EscapeString(page.Message) + `</p>` + qr + `<nav>` + networkLinks + `</nav><footer><span>` + html.EscapeString(formatPairingExpiry(page.ExpiresAt)) + `</span>` + regenerate + `</footer></main></body></html>`
	_, _ = response.Write([]byte(body))
}

const trayPairingCSS = `*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;padding:24px;background:linear-gradient(145deg,#e8f5fc,#cfe3ef);color:#15344a;font:600 14px/1.55 "Microsoft YaHei",sans-serif}main{width:min(520px,100%);padding:24px;border:1px solid rgba(54,105,135,.3);border-radius:18px;background:rgba(252,254,255,.92);box-shadow:0 18px 50px rgba(23,63,99,.18);text-align:center}header{display:flex;align-items:center;justify-content:center;gap:12px}header b{display:grid;place-items:center;width:46px;height:46px;border-radius:12px;background:#ffd65a;font-size:22px}small{letter-spacing:.16em;color:#648497}h1{margin:1px 0 0;font-size:24px}p{color:#52738c}img{display:block;max-width:100%;height:auto;margin:16px auto;border:10px solid white;border-radius:12px}nav{display:grid;gap:7px;margin-top:13px}nav a,.regenerate{padding:8px 10px;border:1px solid rgba(43,117,157,.22);border-radius:8px;color:#2b759d;text-decoration:none}nav a.selected{border-color:#e8a91d;background:#fff5c8;color:#5b4100}footer{display:flex;justify-content:space-between;gap:10px;align-items:center;margin-top:14px;color:#7892a2;font-size:10px}form{margin:0}.regenerate{padding:6px 9px;background:transparent;color:#a13a40;font:inherit;cursor:pointer}`

func sameOriginTrayPairingRequest(request *http.Request) bool {
	origin := request.Header.Get("Origin")
	if origin == "" || request.Host == "" {
		return false
	}
	parsed, err := url.Parse(origin)
	return err == nil && parsed.Scheme == "http" && parsed.Host == request.Host &&
		isLoopbackHost(parsed.Hostname()) && parsed.User == nil && parsed.Path == "" &&
		parsed.RawQuery == "" && parsed.Fragment == ""
}

func selectedPairingNetwork(request *http.Request, networks []mobileNetworkCandidate) int {
	index, err := strconv.Atoi(request.URL.Query().Get("network"))
	if err != nil || index < 0 || index >= len(networks) {
		return 0
	}
	return index
}

func trayPairingHandoffURL(descriptor mobilePairingDescriptor, selected int) string {
	localPage := descriptor.Networks[selected].Endpoint + "mobile/Enhanced/"
	handoff := &url.URL{Scheme: "https", Host: "bomana.ruikang.wang", Path: "/mobile/Enhanced/"}
	fragment := url.Values{
		"mobile-lan":      []string{localPage},
		"mobile-pairing":  []string{descriptor.PairingToken},
		"bridge-pairing":  []string{descriptor.BridgePairingID},
		"pairing-expires": []string{descriptor.PairingExpiresAt},
		"mobile-tray":     []string{"1"},
	}
	handoff.Fragment = fragment.Encode()
	return handoff.String()
}

func formatPairingExpiry(raw string) string {
	value, err := time.Parse(time.RFC3339, raw)
	if err != nil {
		return "短时间内有效"
	}
	return "有效至本机时间 " + value.Local().Format("15:04:05")
}
