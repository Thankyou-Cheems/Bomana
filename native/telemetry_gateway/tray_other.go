//go:build !windows

package main

type trayController struct{}

func startTray(trayConfig) (*trayController, error) { return nil, nil }

func (*trayController) Close() {}
