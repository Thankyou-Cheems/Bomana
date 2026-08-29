package main

import (
	"context"
	"encoding/csv"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

const (
	bridgePortStart = 8878
	bridgePortEnd   = 8897
	officialOrigin  = "https://bomana.ruikang.wang"
	latestBridgeURL = "https://bomana.ruikang.wang/downloads/bridge-release.json"
	requestTimeout  = 4 * time.Second
	maxJSONBytes    = 512 * 1024
)

type capabilities struct {
	SchemaVersion   int    `json:"schema_version"`
	BridgeProtocol  int    `json:"bridge_protocol"`
	CacheProtocol   int    `json:"cache_protocol"`
	BridgeVersion   string `json:"bridge_version"`
	AppWebVersion   string `json:"app_web_version"`
	Input           string `json:"input"`
	WriteCommands   bool   `json:"write_commands"`
	BuildProvenance string `json:"build_provenance"`
	Authenticode    bool   `json:"authenticode"`
}

type httpCheck struct {
	Status      int
	Elapsed     time.Duration
	ContentType string
	JSONKeys    []string
	Error       string
}

type preflightCheck struct {
	Status              int
	Elapsed             time.Duration
	AllowOrigin         string
	AllowMethods        string
	AllowHeaders        string
	AllowPrivateNetwork string
	Error               string
}

type bridgePortCheck struct {
	Port         int
	TCPReachable bool
	TCPElapsed   time.Duration
	TCPError     string
	Capabilities httpCheck
	Identity     capabilities
	Preflight    preflightCheck
	Relay8111    httpCheck
}

type releaseCheck struct {
	HTTPCheck httpCheck
	Version   string
	SHA256    string
}

type diagnosticSnapshot struct {
	CapturedAt   time.Time
	OS           string
	Architecture string
	BridgeTasks  []string
	EdgeVersion  string
	EdgePolicies []string
	Ports        []bridgePortCheck
	Game8111     httpCheck
	Latest       releaseCheck
}

type diagnosis struct {
	Code    string
	Summary string
	Actions []string
}

func main() {
	outputPath := flag.String("output", "", "optional diagnostic report path")
	noOpen := flag.Bool("no-open", false, "do not open the report in Notepad")
	flag.Parse()
	fmt.Println("Bomana Bridge 自动诊断正在运行，请稍候……")
	snapshot := collectDiagnostics()
	result := diagnose(snapshot)
	report := formatReport(snapshot, result)
	path, err := writeReport(report, snapshot.CapturedAt, *outputPath)
	if err != nil {
		fmt.Printf("无法保存诊断报告：%v\n", err)
		return
	}
	fmt.Printf("诊断完成：%s\n", path)
	if runtime.GOOS == "windows" && !*noOpen {
		if err := exec.Command("notepad.exe", path).Start(); err != nil {
			fmt.Printf("请手动打开报告：%s\n", path)
		}
	}
}

func collectDiagnostics() diagnosticSnapshot {
	transport := http.DefaultTransport.(*http.Transport).Clone()
	transport.Proxy = nil
	transport.DisableKeepAlives = true
	client := &http.Client{
		Transport: transport,
		Timeout:   requestTimeout,
		CheckRedirect: func(_ *http.Request, _ []*http.Request) error {
			return http.ErrUseLastResponse
		},
	}

	ports := make([]bridgePortCheck, bridgePortEnd-bridgePortStart+1)
	var wait sync.WaitGroup
	for port := bridgePortStart; port <= bridgePortEnd; port++ {
		index := port - bridgePortStart
		wait.Add(1)
		go func() {
			defer wait.Done()
			ports[index] = inspectBridgePort(client, port)
		}()
	}
	wait.Wait()

	return diagnosticSnapshot{
		CapturedAt:   time.Now().UTC(),
		OS:           runtime.GOOS,
		Architecture: runtime.GOARCH,
		BridgeTasks:  bridgeTaskFacts(),
		EdgeVersion:  edgeVersion(),
		EdgePolicies: edgePolicyFacts(),
		Ports:        ports,
		Game8111:     inspectJSON(client, "http://127.0.0.1:8111/state", ""),
		Latest:       inspectLatestRelease(client),
	}
}

func inspectBridgePort(client *http.Client, port int) bridgePortCheck {
	address := net.JoinHostPort("127.0.0.1", strconv.Itoa(port))
	started := time.Now()
	connection, err := net.DialTimeout("tcp", address, 1200*time.Millisecond)
	result := bridgePortCheck{Port: port, TCPElapsed: time.Since(started)}
	if err != nil {
		result.TCPError = compactError(err)
		return result
	}
	result.TCPReachable = true
	_ = connection.Close()

	base := "http://" + address
	result.Capabilities, result.Identity = inspectCapabilities(client, base+"/api/v1/capabilities")
	result.Preflight = inspectPreflight(client, base+"/api/v1/capabilities")
	result.Relay8111 = inspectJSON(client, base+"/api/v1/8111/state", officialOrigin)
	return result
}

func inspectCapabilities(client *http.Client, rawURL string) (httpCheck, capabilities) {
	check, body := requestBytes(client, http.MethodGet, rawURL, officialOrigin, nil)
	var identity capabilities
	if check.Error == "" && check.Status == http.StatusOK {
		if err := json.Unmarshal(body, &identity); err != nil {
			check.Error = "invalid capabilities JSON"
		}
	}
	return check, identity
}

func inspectPreflight(client *http.Client, rawURL string) preflightCheck {
	request, _ := http.NewRequest(http.MethodOptions, rawURL, nil)
	request.Header.Set("Origin", officialOrigin)
	request.Header.Set("Access-Control-Request-Method", "GET")
	request.Header.Set("Access-Control-Request-Headers", "accept")
	request.Header.Set("Access-Control-Request-Private-Network", "true")
	started := time.Now()
	response, err := client.Do(request)
	result := preflightCheck{Elapsed: time.Since(started)}
	if err != nil {
		result.Error = compactError(err)
		return result
	}
	defer response.Body.Close()
	_, _ = io.Copy(io.Discard, io.LimitReader(response.Body, 8*1024))
	result.Status = response.StatusCode
	result.AllowOrigin = response.Header.Get("Access-Control-Allow-Origin")
	result.AllowMethods = response.Header.Get("Access-Control-Allow-Methods")
	result.AllowHeaders = response.Header.Get("Access-Control-Allow-Headers")
	result.AllowPrivateNetwork = response.Header.Get("Access-Control-Allow-Private-Network")
	return result
}

func inspectJSON(client *http.Client, rawURL, origin string) httpCheck {
	check, body := requestBytes(client, http.MethodGet, rawURL, origin, nil)
	if check.Error != "" || check.Status != http.StatusOK {
		return check
	}
	var value any
	if err := json.Unmarshal(body, &value); err != nil {
		check.Error = "response is not JSON"
		return check
	}
	if object, ok := value.(map[string]any); ok {
		check.JSONKeys = make([]string, 0, len(object))
		for key := range object {
			check.JSONKeys = append(check.JSONKeys, key)
		}
		sort.Strings(check.JSONKeys)
	}
	return check
}

func requestBytes(client *http.Client, method, rawURL, origin string, headers map[string]string) (httpCheck, []byte) {
	ctx, cancel := context.WithTimeout(context.Background(), requestTimeout)
	defer cancel()
	request, _ := http.NewRequestWithContext(ctx, method, rawURL, nil)
	request.Header.Set("Accept", "application/json")
	if origin != "" {
		request.Header.Set("Origin", origin)
	}
	for key, value := range headers {
		request.Header.Set(key, value)
	}
	started := time.Now()
	response, err := client.Do(request)
	check := httpCheck{Elapsed: time.Since(started)}
	if err != nil {
		check.Error = compactError(err)
		return check, nil
	}
	defer response.Body.Close()
	check.Status = response.StatusCode
	check.ContentType = response.Header.Get("Content-Type")
	body, err := io.ReadAll(io.LimitReader(response.Body, maxJSONBytes+1))
	if err != nil {
		check.Error = compactError(err)
	} else if len(body) > maxJSONBytes {
		check.Error = "response exceeded diagnostic limit"
		body = nil
	}
	return check, body
}

func inspectLatestRelease(client *http.Client) releaseCheck {
	check, body := requestBytes(client, http.MethodGet, latestBridgeURL, "", nil)
	result := releaseCheck{HTTPCheck: check}
	if check.Error != "" || check.Status != http.StatusOK {
		return result
	}
	var payload struct {
		Version string `json:"bridge_version"`
		SHA256  string `json:"bridge_sha256"`
	}
	if err := json.Unmarshal(body, &payload); err != nil {
		result.HTTPCheck.Error = "invalid release JSON"
		return result
	}
	result.Version = payload.Version
	result.SHA256 = payload.SHA256
	return result
}

func diagnose(snapshot diagnosticSnapshot) diagnosis {
	reachable := make([]bridgePortCheck, 0, len(snapshot.Ports))
	accepted := make([]bridgePortCheck, 0, 1)
	for _, port := range snapshot.Ports {
		if port.TCPReachable {
			reachable = append(reachable, port)
		}
		if validBridgeIdentity(port) {
			accepted = append(accepted, port)
		}
	}
	if len(reachable) == 0 {
		return diagnosis{
			Code:    "BRIDGE_NOT_LISTENING",
			Summary: "未在 8878–8897 发现 Bridge 监听端口。",
			Actions: []string{"从托盘退出所有 Bridge 后重新运行下载文件。", "若托盘存在但仍无监听端口，请将 BomanaBridge.exe 加入安全软件允许列表。"},
		}
	}
	if len(accepted) == 0 {
		return diagnosis{
			Code:    "BRIDGE_PROTOCOL_MISMATCH",
			Summary: "端口存在，但没有端口返回当前 Bridge 协议。",
			Actions: []string{"确认托盘“关于 Bomana”中的版本并退出旧进程。", "重新下载并运行当前 BomanaBridge.exe。"},
		}
	}
	bridge := accepted[0]
	if !validPreflight(bridge.Preflight) {
		return diagnosis{
			Code:    "BRIDGE_BROWSER_PREFLIGHT_FAILED",
			Summary: "Bridge 存在，但 Edge 所需的 CORS/LNA 预检不完整。",
			Actions: []string{"将本报告发送给 Bomana 开发者。"},
		}
	}
	if snapshot.Game8111.Status != http.StatusOK || snapshot.Game8111.Error != "" {
		return diagnosis{
			Code:    "GAME_8111_UNAVAILABLE",
			Summary: "Bridge 正常，但游戏原始 8111 当前不可访问。",
			Actions: []string{"进入实际对局后重新运行诊断。", "检查是否有其他程序占用 8111 或安全软件阻止本机访问。"},
		}
	}
	if bridge.Relay8111.Status != http.StatusOK || bridge.Relay8111.Error != "" {
		return diagnosis{
			Code:    "BRIDGE_8111_RELAY_FAILED",
			Summary: "游戏原始 8111 正常，但 Bridge 转发失败。",
			Actions: []string{"将 BomanaBridge.exe 加入安全软件允许列表。", "将本报告发送给 Bomana 开发者。"},
		}
	}
	return diagnosis{
		Code:    "LOCAL_CHAIN_OK",
		Summary: "Bridge、本机 8111、转发与 Edge 预检均正常；故障位于 Edge 页面侧。",
		Actions: []string{"检查 edge://policy 中的 LocalNetwork/Loopback 策略。", "暂时禁用会代理本机请求的 Edge 扩展或 VPN 后重试。", "将本报告发送给 Bomana 开发者。"},
	}
}

func validBridgeIdentity(port bridgePortCheck) bool {
	identity := port.Identity
	return port.Capabilities.Status == http.StatusOK && port.Capabilities.Error == "" &&
		identity.SchemaVersion == 1 && identity.BridgeProtocol == 1 && identity.CacheProtocol == 4 &&
		identity.Input == "official-8111-only" && !identity.WriteCommands
}

func validPreflight(check preflightCheck) bool {
	return check.Status == http.StatusNoContent && check.Error == "" &&
		check.AllowOrigin == officialOrigin && strings.Contains(check.AllowMethods, "GET") &&
		strings.EqualFold(check.AllowPrivateNetwork, "true")
}

func formatReport(snapshot diagnosticSnapshot, result diagnosis) string {
	var report strings.Builder
	fmt.Fprintln(&report, "Bomana Bridge 诊断报告")
	fmt.Fprintln(&report, "========================")
	fmt.Fprintf(&report, "诊断时间（UTC）：%s\n", snapshot.CapturedAt.Format(time.RFC3339))
	fmt.Fprintf(&report, "系统：%s/%s\n", snapshot.OS, snapshot.Architecture)
	fmt.Fprintf(&report, "Edge 版本：%s\n", fallback(snapshot.EdgeVersion, "未读取到"))
	fmt.Fprintf(&report, "结论代码：%s\n", result.Code)
	fmt.Fprintf(&report, "结论：%s\n", result.Summary)
	for _, action := range result.Actions {
		fmt.Fprintf(&report, "- %s\n", action)
	}

	fmt.Fprintln(&report, "\nBridge 进程")
	if len(snapshot.BridgeTasks) == 0 {
		fmt.Fprintln(&report, "- tasklist 未发现 BomanaBridge.exe")
	} else {
		for _, task := range snapshot.BridgeTasks {
			fmt.Fprintf(&report, "- %s\n", task)
		}
	}

	fmt.Fprintln(&report, "\n端口与协议")
	for _, port := range snapshot.Ports {
		if !port.TCPReachable {
			continue
		}
		fmt.Fprintf(&report, "- 127.0.0.1:%d TCP=OK(%s) capabilities=%s\n", port.Port, duration(port.TCPElapsed), describeHTTP(port.Capabilities))
		fmt.Fprintf(&report, "  Bridge=%s AppWeb=%s schema=%d bridge_protocol=%d cache_protocol=%d provenance=%s authenticode=%t\n",
			fallback(port.Identity.BridgeVersion, "--"), fallback(port.Identity.AppWebVersion, "--"), port.Identity.SchemaVersion,
			port.Identity.BridgeProtocol, port.Identity.CacheProtocol, fallback(port.Identity.BuildProvenance, "--"), port.Identity.Authenticode)
		fmt.Fprintf(&report, "  preflight=%s allow_origin=%q allow_private_network=%q\n", describePreflight(port.Preflight), port.Preflight.AllowOrigin, port.Preflight.AllowPrivateNetwork)
		fmt.Fprintf(&report, "  relay_8111=%s\n", describeHTTP(port.Relay8111))
	}

	fmt.Fprintln(&report, "\n8111 与线上版本")
	fmt.Fprintf(&report, "- game_8111=%s\n", describeHTTP(snapshot.Game8111))
	fmt.Fprintf(&report, "- latest_bridge=%s sha256=%s request=%s\n", fallback(snapshot.Latest.Version, "--"), shortHash(snapshot.Latest.SHA256), describeHTTP(snapshot.Latest.HTTPCheck))

	fmt.Fprintln(&report, "\nEdge 策略（只报告是否存在，不记录 URL 列表）")
	if len(snapshot.EdgePolicies) == 0 {
		fmt.Fprintln(&report, "- 未发现已配置的 LocalNetwork/Loopback 策略")
	} else {
		for _, policy := range snapshot.EdgePolicies {
			fmt.Fprintf(&report, "- %s\n", policy)
		}
	}

	fmt.Fprintln(&report, "\n隐私说明")
	fmt.Fprintln(&report, "本报告不保存账号、配对码、授权头、游戏字段值、地图、聊天或 8111 原始正文；JSON 仅记录字段名。")
	return report.String()
}

func describeHTTP(check httpCheck) string {
	parts := []string{fmt.Sprintf("status=%d", check.Status), "elapsed=" + duration(check.Elapsed)}
	if check.ContentType != "" {
		parts = append(parts, "type="+check.ContentType)
	}
	if len(check.JSONKeys) > 0 {
		parts = append(parts, "json_keys="+strings.Join(check.JSONKeys, ","))
	}
	if check.Error != "" {
		parts = append(parts, "error="+check.Error)
	}
	return strings.Join(parts, " ")
}

func describePreflight(check preflightCheck) string {
	parts := []string{fmt.Sprintf("status=%d", check.Status), "elapsed=" + duration(check.Elapsed)}
	if check.Error != "" {
		parts = append(parts, "error="+check.Error)
	}
	return strings.Join(parts, " ")
}

func bridgeTaskFacts() []string {
	if runtime.GOOS != "windows" {
		return nil
	}
	output, err := exec.Command("tasklist.exe", "/FI", "IMAGENAME eq BomanaBridge.exe", "/FO", "CSV", "/NH").Output()
	if err != nil {
		return nil
	}
	reader := csv.NewReader(strings.NewReader(string(output)))
	rows, err := reader.ReadAll()
	if err != nil {
		return nil
	}
	results := make([]string, 0, len(rows))
	for _, row := range rows {
		if len(row) >= 2 && strings.EqualFold(strings.TrimSpace(row[0]), "BomanaBridge.exe") {
			results = append(results, fmt.Sprintf("%s PID=%s", row[0], row[1]))
		}
	}
	return results
}

func edgeVersion() string {
	if runtime.GOOS != "windows" {
		return ""
	}
	for _, root := range []string{`HKCU\Software\Microsoft\Edge\BLBeacon`, `HKLM\Software\Microsoft\Edge\BLBeacon`} {
		output, err := exec.Command("reg.exe", "query", root, "/v", "version").CombinedOutput()
		if err == nil {
			fields := strings.Fields(string(output))
			if len(fields) > 0 {
				return fields[len(fields)-1]
			}
		}
	}
	return ""
}

func edgePolicyFacts() []string {
	if runtime.GOOS != "windows" {
		return nil
	}
	policies := []string{
		"LocalNetworkAccessRestrictionsEnabled",
		"LocalNetworkAccessRestrictionsTemporaryOptOut",
		"LocalNetworkAccessAllowedForUrls",
		"LocalNetworkAccessBlockedForUrls",
		"LocalNetworkAllowedForUrls",
		"LocalNetworkBlockedForUrls",
		"LoopbackNetworkAccessAllowedForUrls",
		"LoopbackNetworkAccessBlockedForUrls",
		"LoopbackNetworkAllowedForUrls",
		"LoopbackNetworkBlockedForUrls",
	}
	results := make([]string, 0)
	for _, hive := range []string{"HKCU", "HKLM"} {
		root := hive + `\SOFTWARE\Policies\Microsoft\Edge`
		for _, policy := range policies {
			valueOutput, valueErr := exec.Command("reg.exe", "query", root, "/v", policy).CombinedOutput()
			keyErr := exec.Command("reg.exe", "query", root+`\`+policy).Run()
			if valueErr == nil {
				results = append(results, fmt.Sprintf("%s %s value=%s", hive, policy, lastField(valueOutput)))
			} else if keyErr == nil {
				results = append(results, fmt.Sprintf("%s %s list=present", hive, policy))
			}
		}
	}
	sort.Strings(results)
	return results
}

func writeReport(report string, capturedAt time.Time, requestedPath string) (string, error) {
	if strings.TrimSpace(requestedPath) != "" {
		path, err := filepath.Abs(requestedPath)
		if err != nil {
			return "", err
		}
		return path, os.WriteFile(path, []byte(report), 0o600)
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return "", err
	}
	desktop := filepath.Join(home, "Desktop")
	if info, statErr := os.Stat(desktop); statErr != nil || !info.IsDir() {
		desktop = home
	}
	name := "BomanaBridge诊断报告-" + capturedAt.Local().Format("20060102-150405") + ".txt"
	path := filepath.Join(desktop, name)
	return path, os.WriteFile(path, []byte(report), 0o600)
}

func compactError(err error) string {
	if err == nil {
		return ""
	}
	text := strings.ReplaceAll(err.Error(), "\r", " ")
	text = strings.ReplaceAll(text, "\n", " ")
	if len(text) > 220 {
		text = text[:220] + "…"
	}
	return text
}

func duration(value time.Duration) string {
	return strconv.FormatInt(value.Milliseconds(), 10) + "ms"
}

func shortHash(value string) string {
	if len(value) < 16 {
		return fallback(value, "--")
	}
	return value[:12] + "…" + value[len(value)-4:]
}

func fallback(value, replacement string) string {
	if strings.TrimSpace(value) == "" {
		return replacement
	}
	return strings.TrimSpace(value)
}

func lastField(value []byte) string {
	fields := strings.Fields(string(value))
	if len(fields) == 0 {
		return "present"
	}
	return fields[len(fields)-1]
}
