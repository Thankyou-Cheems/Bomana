package main

import (
	"crypto/subtle"
	"encoding/base64"
	"errors"
	"fmt"
	"html"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"

	qrcode "github.com/skip2/go-qrcode"
)

func (gateway *relay) serveTrayMobilePairing(response http.ResponseWriter, request *http.Request) {
	if request.RemoteAddr != "" && !isLoopbackRemote(request.RemoteAddr) {
		http.Error(response, "loopback required", http.StatusForbidden)
		return
	}
	if request.Method == http.MethodPost {
		edition, valid := selectedTrayPairingEdition(request)
		if !valid || !trayPairingRotationRequest(request) || !gateway.authorizeTrayPairingRotation(response, request) {
			http.Error(response, "origin forbidden", http.StatusForbidden)
			return
		}
		if request.URL.Query().Has("network-address") {
			current, _, ok := gateway.mobile.Current(time.Now())
			if !ok || selectedPairingNetwork(request, current.Networks) < 0 {
				http.Error(response, "selected network unavailable", http.StatusConflict)
				return
			}
		}
		pageToken := ""
		if !sameOriginTrayPairingRequest(request) {
			pageToken = request.PostForm.Get("pairing-token")
		}
		descriptor, err := gateway.mobile.rotateTrayEdition(gateway, time.Now(), edition, request.URL.Query().Get("network-address"), pageToken)
		if err != nil {
			if errors.Is(err, errTrayPairingNetworkUnavailable) {
				http.Error(response, "selected network unavailable", http.StatusConflict)
				return
			}
			if errors.Is(err, errTrayPairingRotationUnauthorized) {
				http.Error(response, "origin forbidden", http.StatusForbidden)
				return
			}
			http.Error(response, "mobile pairing unavailable", http.StatusServiceUnavailable)
			return
		}
		response.Header().Set("Cache-Control", "no-store")
		selectionQuery := url.Values{}
		if edition == mobileEditionStandard {
			selectionQuery.Set("edition", "Standard")
		}
		if selected := selectedPairingNetwork(request, descriptor.Networks); selected > 0 {
			selectionQuery.Set("network", strconv.Itoa(selected))
		}
		if address := request.URL.Query().Get("network-address"); address != "" {
			selectionQuery.Set("network-address", address)
		}
		location := "/mobile-pairing"
		if len(selectionQuery) > 0 {
			location += "?" + selectionQuery.Encode()
		}
		response.Header().Set("Location", location)
		response.WriteHeader(http.StatusSeeOther)
		return
	}
	if request.Method != http.MethodGet && request.Method != http.MethodHead {
		response.Header().Set("Allow", "GET, HEAD, POST")
		http.Error(response, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	edition, valid := selectedTrayPairingEdition(request)
	if !valid {
		http.Error(response, "invalid mobile edition", http.StatusBadRequest)
		return
	}
	now := time.Now()
	currentDescriptor, currentClaimed, currentOK := gateway.mobile.Current(now)
	if _, explicitlySelected := request.URL.Query()["edition"]; !explicitlySelected && currentOK {
		edition = currentDescriptor.Edition
	}
	if currentOK && currentClaimed && currentDescriptor.Edition == edition {
		selected := selectedPairingNetwork(request, currentDescriptor.Networks)
		if redirectIndexedPairingNetwork(response, request, currentDescriptor.Networks, selected) {
			return
		}
		writeTrayPairingPage(response, trayPairingPage{
			Title:             "手机已连接",
			Message:           "当前手机会话仍然有效。关闭电脑网页不会中断手机；请保持 Bridge 运行。",
			ExpiresAt:         currentDescriptor.ExpiresAt,
			RegenerationToken: currentDescriptor.PairingToken,
			Edition:           currentDescriptor.Edition,
			Networks:          currentDescriptor.Networks,
			Selected:          selected,
			NetworkAddress:    request.URL.Query().Get("network-address"),
		}, request.Method == http.MethodHead)
		return
	}
	descriptor, err := gateway.mobile.StartEdition(gateway, now, edition, false)
	if err != nil {
		http.Error(response, "mobile pairing unavailable", http.StatusServiceUnavailable)
		return
	}
	selected := selectedPairingNetwork(request, descriptor.Networks)
	if redirectIndexedPairingNetwork(response, request, descriptor.Networks, selected) {
		return
	}
	qrData := ""
	if selected >= 0 {
		pairingURL := trayPairingHandoffURL(descriptor, selected)
		png, err := qrcode.Encode(pairingURL, qrcode.Medium, 300)
		if err != nil {
			http.Error(response, "QR generation failed", http.StatusInternalServerError)
			return
		}
		qrData = "data:image/png;base64," + base64.StdEncoding.EncodeToString(png)
	}
	message := "普通版为公开功能，扫码后直接连接 Bridge，不需要 CheemsPay 登录。"
	if edition == mobileEditionEnhanced {
		message = "超级爆弹版需要 Enhanced 权益；手机若尚未授权，会先在手机上登录 CheemsPay。"
	}
	writeTrayPairingPage(response, trayPairingPage{
		Title:             "连接手机",
		Message:           message,
		ExpiresAt:         descriptor.PairingExpiresAt,
		QRCodeData:        qrData,
		Networks:          descriptor.Networks,
		Selected:          selected,
		NetworkAddress:    request.URL.Query().Get("network-address"),
		RegenerationToken: descriptor.PairingToken,
		Edition:           descriptor.Edition,
	}, request.Method == http.MethodHead)
}

type trayPairingPage struct {
	Title             string
	Message           string
	ExpiresAt         string
	QRCodeData        string
	Networks          []mobileNetworkCandidate
	Selected          int
	NetworkAddress    string
	RegenerationToken string
	Edition           mobileEdition
}

func writeTrayPairingPage(response http.ResponseWriter, page trayPairingPage, head bool) {
	if page.Selected < 0 {
		page.Title = "重新选择局域网"
		page.Message = "已选择的网卡地址不再可用，请选择与手机同一 Wi-Fi 的当前地址。"
		page.QRCodeData = ""
		page.RegenerationToken = ""
	} else if page.Selected < len(page.Networks) {
		page.NetworkAddress = page.Networks[page.Selected].Address
	}
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
	editionQuery := ""
	if page.Edition == mobileEditionStandard {
		editionQuery = "&edition=Standard"
	}
	for index, candidate := range page.Networks {
		className := ""
		if index == page.Selected {
			className = ` class="selected"`
		}
		networkLinks += fmt.Sprintf(`<a%s href="/mobile-pairing?network=%d%s&amp;network-address=%s">%s · %s</a>`, className, index, editionQuery, url.QueryEscape(candidate.Address), html.EscapeString(candidate.Interface), html.EscapeString(candidate.Address))
	}
	standardClass := ""
	enhancedClass := ""
	if page.Edition == mobileEditionStandard {
		standardClass = ` class="selected"`
	} else {
		enhancedClass = ` class="selected"`
	}
	networkQuery := ""
	if page.Selected > 0 {
		networkQuery = "&amp;network=" + strconv.Itoa(page.Selected)
	}
	if page.NetworkAddress != "" {
		networkQuery += "&amp;network-address=" + url.QueryEscape(page.NetworkAddress)
	}
	editionLinks := `<nav class="editions" aria-label="选择手机版本"><a` + standardClass + ` href="/mobile-pairing?edition=Standard` + networkQuery + `">普通版</a><a` + enhancedClass + ` href="/mobile-pairing?edition=Enhanced` + networkQuery + `">超级爆弹版</a></nav>`
	qr := ""
	if page.QRCodeData != "" {
		qr = `<img src="` + html.EscapeString(page.QRCodeData) + `" alt="Bomana 手机配对二维码" width="300" height="300">`
	}
	regenerate := ""
	if page.RegenerationToken != "" {
		action := "/mobile-pairing?rotate=1"
		if page.Edition == mobileEditionStandard {
			action = "/mobile-pairing?edition=Standard&amp;rotate=1"
		}
		action += networkQuery
		regenerate = `<form method="post" action="` + action + `"><input type="hidden" name="pairing-token" value="` + html.EscapeString(page.RegenerationToken) + `"><button class="regenerate" type="submit">重新生成并撤销旧会话</button></form>`
	}
	body := `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>` + html.EscapeString(page.Title) + ` · Bomana Bridge</title><style>` + trayPairingCSS + `</style></head><body><main><header><b>B</b><div><small>BOMANA BRIDGE</small><h1>` + html.EscapeString(page.Title) + `</h1></div></header>` + editionLinks + `<p>` + html.EscapeString(page.Message) + `</p>` + qr + `<nav>` + networkLinks + `</nav><footer><span>` + html.EscapeString(formatPairingExpiry(page.ExpiresAt)) + `</span>` + regenerate + `</footer></main></body></html>`
	_, _ = response.Write([]byte(body))
}

const trayPairingCSS = `*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;padding:24px;background:linear-gradient(145deg,#e8f5fc,#cfe3ef);color:#15344a;font:600 14px/1.55 "Microsoft YaHei",sans-serif}main{width:min(520px,100%);padding:24px;border:1px solid rgba(54,105,135,.3);border-radius:18px;background:rgba(252,254,255,.92);box-shadow:0 18px 50px rgba(23,63,99,.18);text-align:center}header{display:flex;align-items:center;justify-content:center;gap:12px}header b{display:grid;place-items:center;width:46px;height:46px;border-radius:12px;background:#ffd65a;font-size:22px}small{letter-spacing:.16em;color:#648497}h1{margin:1px 0 0;font-size:24px}p{color:#52738c}img{display:block;max-width:100%;height:auto;margin:16px auto;border:10px solid white;border-radius:12px}nav{display:grid;gap:7px;margin-top:13px}.editions{grid-template-columns:1fr 1fr;margin-top:18px}nav a,.regenerate{padding:8px 10px;border:1px solid rgba(43,117,157,.22);border-radius:8px;color:#2b759d;text-decoration:none}nav a.selected{border-color:#e8a91d;background:#fff5c8;color:#5b4100}footer{display:flex;justify-content:space-between;gap:10px;align-items:center;margin-top:14px;color:#7892a2;font-size:10px}form{margin:0}.regenerate{padding:6px 9px;background:transparent;color:#a13a40;font:inherit;cursor:pointer}`

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

func (gateway *relay) authorizeTrayPairingRotation(response http.ResponseWriter, request *http.Request) bool {
	if sameOriginTrayPairingRequest(request) {
		return true
	}
	descriptor, _, ok := gateway.mobile.Current(time.Now())
	if !ok || descriptor.PairingToken == "" || request.Body == nil {
		return false
	}
	request.Body = http.MaxBytesReader(response, request.Body, 4*1024)
	if err := request.ParseForm(); err != nil {
		return false
	}
	candidate := request.PostForm.Get("pairing-token")
	return candidate != "" && subtle.ConstantTimeCompare([]byte(candidate), []byte(descriptor.PairingToken)) == 1
}

func selectedPairingNetwork(request *http.Request, networks []mobileNetworkCandidate) int {
	if addresses, exists := request.URL.Query()["network-address"]; exists {
		if len(addresses) != 1 {
			return -1
		}
		for index, candidate := range networks {
			if candidate.Address == addresses[0] {
				return index
			}
		}
		return -1
	}
	index, err := strconv.Atoi(request.URL.Query().Get("network"))
	if err != nil || index < 0 || index >= len(networks) {
		return 0
	}
	return index
}

// Pin legacy numeric selection URLs once, so refreshing cannot select another IP
// merely because the interface list changed order.
func redirectIndexedPairingNetwork(response http.ResponseWriter, request *http.Request, networks []mobileNetworkCandidate, selected int) bool {
	query := request.URL.Query()
	if selected < 0 || !query.Has("network") || query.Has("network-address") {
		return false
	}
	query.Set("network-address", networks[selected].Address)
	response.Header().Set("Cache-Control", "no-store")
	response.Header().Set("Location", "/mobile-pairing?"+query.Encode())
	response.WriteHeader(http.StatusFound)
	return true
}

func selectedTrayPairingEdition(request *http.Request) (mobileEdition, bool) {
	values, exists := request.URL.Query()["edition"]
	if !exists {
		return mobileEditionEnhanced, true
	}
	if len(values) != 1 {
		return "", false
	}
	edition := mobileEdition(values[0])
	return edition, validMobileEdition(edition)
}

func trayPairingRotationRequest(request *http.Request) bool {
	query := request.URL.Query()
	rotate := query["rotate"]
	if len(rotate) != 1 || rotate[0] != "1" {
		return false
	}
	for key := range query {
		if key != "rotate" && key != "edition" && key != "network" && key != "network-address" {
			return false
		}
	}
	return true
}

func trayPairingHandoffURL(descriptor mobilePairingDescriptor, selected int) string {
	edition := descriptor.Edition
	if !validMobileEdition(edition) {
		edition = mobileEditionEnhanced
	}
	localPage := descriptor.Networks[selected].Endpoint + "mobile/" + string(edition) + "/"
	if edition == mobileEditionStandard {
		target := &url.URL{Scheme: "http", Host: strings.TrimPrefix(strings.TrimSuffix(descriptor.Networks[selected].Endpoint, "/"), "http://"), Path: "/mobile/Standard/"}
		target.Fragment = url.Values{
			"mobile-edition": []string{string(edition)},
			"mobile-pairing": []string{descriptor.PairingToken},
		}.Encode()
		return target.String()
	}
	handoff := &url.URL{Scheme: "https", Host: "bomana.ruikang.wang", Path: "/mobile/Enhanced/"}
	handoff.RawQuery = url.Values{"handoff": []string{"bridge-tray"}}.Encode()
	fragment := url.Values{
		"mobile-edition":  []string{string(edition)},
		"mobile-lan":      []string{localPage},
		"mobile-pairing":  []string{descriptor.PairingToken},
		"bridge-pairing":  []string{descriptor.BridgePairingID},
		"pairing-expires": []string{descriptor.PairingExpiresAt},
		"mobile-tray":     []string{"1"},
	}
	return handoff.String() + "#" + fragment.Encode()
}

func formatPairingExpiry(raw string) string {
	value, err := time.Parse(time.RFC3339, raw)
	if err != nil {
		return "短时间内有效"
	}
	return "有效至本机时间 " + value.Local().Format("15:04:05")
}
