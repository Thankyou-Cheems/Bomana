//go:build !windows

package main

// Official Bridge binaries target Windows. Other hosts run transport test fixtures.
func claimBridgeInstance() (func(), bool, error) { return func() {}, true, nil }
