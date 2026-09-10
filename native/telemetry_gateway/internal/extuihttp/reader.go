// Package extuihttp supplies Bridge's standard HTTP transport to the shared
// ExtUI resolver. Basic Desktop supplies its own Windows system transport.
package extuihttp

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"net/url"
)

func NewReader(client *http.Client) func(context.Context, *url.URL, int64) ([]byte, string, error) {
	return func(ctx context.Context, endpoint *url.URL, maxBytes int64) ([]byte, string, error) {
		request, err := http.NewRequestWithContext(ctx, http.MethodGet, endpoint.String(), nil)
		if err != nil {
			return nil, "", err
		}
		request.Header.Set("Accept", "application/json")
		if endpoint.Path == "/icons.ttf" {
			request.Header.Set("Accept", "font/ttf, application/octet-stream")
		}
		response, err := client.Do(request)
		if err != nil {
			return nil, "", err
		}
		defer response.Body.Close()
		if response.StatusCode != http.StatusOK {
			return nil, "", fmt.Errorf("%s returned HTTP %d", endpoint.Path, response.StatusCode)
		}
		body, err := io.ReadAll(io.LimitReader(response.Body, maxBytes+1))
		if int64(len(body)) > maxBytes {
			return nil, "", fmt.Errorf("%s response exceeds %d bytes", endpoint.Path, maxBytes)
		}
		return body, response.Header.Get("Content-Type"), err
	}
}
