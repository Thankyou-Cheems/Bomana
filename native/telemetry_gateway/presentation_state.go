package main

import (
	"errors"
	"regexp"
	"sync"
)

var sharedWeaponID = regexp.MustCompile(`^[A-Za-z0-9_.-]{1,128}$`)

type weaponSelectionState struct {
	SchemaVersion    int    `json:"schema_version"`
	Revision         uint64 `json:"revision"`
	SelectedWeaponID string `json:"selected_weapon_id"`
}

type presentationState struct {
	mu               sync.RWMutex
	revision         uint64
	selectedWeaponID string
}

func newPresentationState() *presentationState { return &presentationState{} }

func (state *presentationState) WeaponSelection() weaponSelectionState {
	state.mu.RLock()
	defer state.mu.RUnlock()
	return weaponSelectionState{SchemaVersion: 1, Revision: state.revision, SelectedWeaponID: state.selectedWeaponID}
}

func (state *presentationState) SelectWeapon(id string) (weaponSelectionState, error) {
	if !sharedWeaponID.MatchString(id) {
		return weaponSelectionState{}, errors.New("invalid shared weapon id")
	}
	state.mu.Lock()
	defer state.mu.Unlock()
	if state.selectedWeaponID != id {
		state.selectedWeaponID = id
		state.revision++
	}
	return weaponSelectionState{SchemaVersion: 1, Revision: state.revision, SelectedWeaponID: state.selectedWeaponID}, nil
}
