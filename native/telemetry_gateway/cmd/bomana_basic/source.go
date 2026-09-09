package main

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/url"
	"sync"
	"time"

	"bomana/native/telemetry_gateway/internal/extui"
)

type source struct {
	resolver *extui.Resolver
	client   *http.Client
	last     frame
	nextMap  int64
}

func newSource(candidates []*url.URL) (*source, error) {
	if candidates == nil {
		candidates = extui.DefaultCandidates()
	}
	client := &http.Client{Timeout: 600 * time.Millisecond, Transport: &http.Transport{Proxy: nil, MaxIdleConnsPerHost: 4}, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	r, err := extui.NewResolver(extui.Options{Candidates: candidates, Client: client})
	return &source{resolver: r, client: client}, err
}
func (s *source) read(ctx context.Context, now int64) frame {
	f := frame{At: now}
	base, err := s.resolver.Resolve(ctx)
	if err != nil {
		return f
	}
	paths := []string{"/indicators", "/state", "/map_objects.json", "/map_info.json"}
	data := make([][]byte, 4)
	errs := make([]error, 4)
	var wg sync.WaitGroup
	readMap := now >= s.nextMap
	for i, path := range paths {
		if i == 3 && !readMap {
			continue
		}
		wg.Add(1)
		go func(i int, path string) { defer wg.Done(); data[i], errs[i] = s.get(ctx, base, path) }(i, path)
	}
	wg.Wait()
	if readMap {
		s.nextMap = now + 1000
	}
	for i, dst := range []*map[string]any{&s.last.Indicators, &s.last.State, nil, &s.last.MapInfo} {
		if i == 2 {
			if errs[i] == nil {
				var raw any
				if json.Unmarshal(data[i], &raw) == nil {
					if wrapper, ok := raw.(map[string]any); ok {
						raw = nil
						for _, k := range []string{"objects", "map_objects", "items", "data"} {
							if list, yes := wrapper[k].([]any); yes {
								raw = list
								break
							}
						}
					}
					if list, ok := raw.([]any); ok {
						records := make([]map[string]any, 0, len(list))
						for _, item := range list {
							if record, yes := item.(map[string]any); yes {
								records = append(records, record)
							}
						}
						s.last.Objects, s.last.ObjectsAt = records, now
					} else {
						errs[i] = errors.New("invalid object array")
					}
				} else {
					errs[i] = errors.New("invalid JSON")
				}
			}
			continue
		}
		if i == 3 && !readMap {
			continue
		}
		if errs[i] != nil {
			continue
		}
		var value map[string]any
		if json.Unmarshal(data[i], &value) != nil || value == nil {
			errs[i] = errors.New("invalid JSON object")
			continue
		}
		*dst = value
		switch i {
		case 0:
			s.last.IndicatorsAt = now
		case 1:
			s.last.StateAt = now
		case 3:
			s.last.MapAt = now
		}
	}
	if errs[0] != nil && errs[1] != nil && errs[2] != nil {
		s.resolver.Invalidate(base)
	}
	if s.last.IndicatorsAt > 0 && now-s.last.IndicatorsAt <= 3000 {
		f.Indicators, f.IndicatorsAt = s.last.Indicators, s.last.IndicatorsAt
	}
	if s.last.StateAt > 0 && now-s.last.StateAt <= 3000 {
		f.State, f.StateAt = s.last.State, s.last.StateAt
	}
	if s.last.ObjectsAt > 0 && now-s.last.ObjectsAt <= 3000 {
		f.Objects, f.ObjectsAt = s.last.Objects, s.last.ObjectsAt
	}
	if s.last.MapAt > 0 && now-s.last.MapAt <= 3000 {
		f.MapInfo, f.MapAt = s.last.MapInfo, s.last.MapAt
	}
	return f
}
func (s *source) get(ctx context.Context, base *url.URL, path string) ([]byte, error) {
	u := *base
	u.Path = path
	r, err := http.NewRequestWithContext(ctx, http.MethodGet, u.String(), nil)
	if err != nil {
		return nil, err
	}
	response, err := s.client.Do(r)
	if err != nil {
		return nil, err
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return nil, errors.New("ExtUI unavailable")
	}
	data, err := io.ReadAll(io.LimitReader(response.Body, 1024*1024+1))
	if len(data) > 1024*1024 {
		return nil, errors.New("ExtUI response exceeds limit")
	}
	return data, err
}
