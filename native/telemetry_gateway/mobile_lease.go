package main

import (
	"crypto/ed25519"
	"crypto/subtle"
	"encoding/base64"
	"encoding/json"
	"errors"
	"strings"
	"time"
)

const (
	mobileLeaseIssuer            = "https://pay.ruikang.wang/api/licenses"
	mobileLeaseAudience          = "bomana:mobile-web"
	mobileLeaseApplication       = "bomana"
	mobileLeaseFeature           = "bomana.super_bomber"
	mobileLeaseType              = "bomana-mobile-access+jwt"
	mobileLeaseProductionKeyID   = "prod-2026-01"
	mobileLeaseProductionKeySPKI = "MCowBQYDK2VwAyEAN30P0bd6DN_fP7iMf1qkzBBkssGMHj0b18B81TsW6n8"
	mobileLeaseClockSkew         = 5 * time.Minute
	mobileLeaseMaximumDuration   = 8 * time.Hour
)

var ed25519SPKIPrefix = []byte{0x30, 0x2a, 0x30, 0x05, 0x06, 0x03, 0x2b, 0x65, 0x70, 0x03, 0x21, 0x00}

type mobileLeaseVerifier func(token string, bridgePairingID string, now time.Time) (time.Time, error)

type mobileLeaseKeyResolver func(keyID string) (ed25519.PublicKey, bool)

type mobileLeaseHeader struct {
	Algorithm string `json:"alg"`
	KeyID     string `json:"kid"`
	Type      string `json:"typ"`
}

type mobileLeaseClaims struct {
	Issuer             string          `json:"iss"`
	Audience           string          `json:"aud"`
	Subject            string          `json:"sub"`
	TokenID            string          `json:"jti"`
	ApplicationID      string          `json:"app_id"`
	RequiredFeature    string          `json:"required_feature"`
	BridgePairingID    string          `json:"bridge_pairing_id"`
	IssuedAt           int64           `json:"iat"`
	ExpiresAt          int64           `json:"exp"`
	ServiceExpiresAt   json.RawMessage `json:"service_expires_at"`
	EntitlementVersion *int64          `json:"entitlement_version"`
}

func verifyMobileEnhancedLease(token string, bridgePairingID string, now time.Time) (time.Time, error) {
	return verifyMobileEnhancedLeaseWithKeys(token, bridgePairingID, now, productionMobileLeaseKey)
}

func verifyMobileEnhancedLeaseWithKeys(
	token string,
	bridgePairingID string,
	now time.Time,
	resolveKey mobileLeaseKeyResolver,
) (time.Time, error) {
	if resolveKey == nil {
		return time.Time{}, errors.New("mobile lease key resolver unavailable")
	}
	if !validMobilePairingID(bridgePairingID) {
		return time.Time{}, errors.New("mobile lease pairing identity invalid")
	}
	if len(token) < 64 || len(token) > 8192 {
		return time.Time{}, errors.New("mobile lease length invalid")
	}
	segments := strings.Split(token, ".")
	if len(segments) != 3 || !validBase64URLSegment(segments[0]) || !validBase64URLSegment(segments[1]) || !validBase64URLSegment(segments[2]) {
		return time.Time{}, errors.New("mobile lease format invalid")
	}
	headerBytes, err := base64.RawURLEncoding.DecodeString(segments[0])
	if err != nil {
		return time.Time{}, errors.New("mobile lease header invalid")
	}
	claimsBytes, err := base64.RawURLEncoding.DecodeString(segments[1])
	if err != nil {
		return time.Time{}, errors.New("mobile lease claims invalid")
	}
	signature, err := base64.RawURLEncoding.DecodeString(segments[2])
	if err != nil || len(signature) != ed25519.SignatureSize {
		return time.Time{}, errors.New("mobile lease signature invalid")
	}
	var header mobileLeaseHeader
	if err := json.Unmarshal(headerBytes, &header); err != nil || header.Algorithm != "EdDSA" || header.Type != mobileLeaseType {
		return time.Time{}, errors.New("mobile lease header invalid")
	}
	publicKey, trusted := resolveKey(header.KeyID)
	if !trusted || len(publicKey) != ed25519.PublicKeySize {
		return time.Time{}, errors.New("mobile lease signing key untrusted")
	}
	signed := []byte(segments[0] + "." + segments[1])
	if !ed25519.Verify(publicKey, signed, signature) {
		return time.Time{}, errors.New("mobile lease signature invalid")
	}
	var claims mobileLeaseClaims
	if err := json.Unmarshal(claimsBytes, &claims); err != nil {
		return time.Time{}, errors.New("mobile lease claims invalid")
	}
	if claims.Issuer != mobileLeaseIssuer ||
		claims.Audience != mobileLeaseAudience ||
		claims.ApplicationID != mobileLeaseApplication ||
		claims.RequiredFeature != mobileLeaseFeature ||
		subtle.ConstantTimeCompare([]byte(claims.BridgePairingID), []byte(bridgePairingID)) != 1 ||
		strings.TrimSpace(claims.Subject) == "" ||
		strings.TrimSpace(claims.TokenID) == "" ||
		claims.EntitlementVersion == nil || *claims.EntitlementVersion < 0 ||
		claims.IssuedAt <= 0 || claims.ExpiresAt <= claims.IssuedAt ||
		claims.ExpiresAt-claims.IssuedAt > int64(mobileLeaseMaximumDuration/time.Second) {
		return time.Time{}, errors.New("mobile lease claims invalid")
	}
	nowUnix := now.Unix()
	if nowUnix < claims.IssuedAt-int64(mobileLeaseClockSkew/time.Second) || nowUnix >= claims.ExpiresAt {
		return time.Time{}, errors.New("mobile lease expired or not yet valid")
	}
	expiresAt := time.Unix(claims.ExpiresAt, 0).UTC()
	serviceExpiresAt, err := parseMobileLeaseServiceExpiry(claims.ServiceExpiresAt)
	if err != nil || (!serviceExpiresAt.IsZero() && expiresAt.After(serviceExpiresAt)) {
		return time.Time{}, errors.New("mobile lease service expiry invalid")
	}
	return expiresAt, nil
}

func productionMobileLeaseKey(keyID string) (ed25519.PublicKey, bool) {
	if keyID != mobileLeaseProductionKeyID {
		return nil, false
	}
	spki, err := base64.RawURLEncoding.DecodeString(mobileLeaseProductionKeySPKI)
	if err != nil || len(spki) != len(ed25519SPKIPrefix)+ed25519.PublicKeySize ||
		subtle.ConstantTimeCompare(spki[:len(ed25519SPKIPrefix)], ed25519SPKIPrefix) != 1 {
		return nil, false
	}
	return ed25519.PublicKey(spki[len(ed25519SPKIPrefix):]), true
}

func parseMobileLeaseServiceExpiry(raw json.RawMessage) (time.Time, error) {
	if len(raw) == 0 {
		return time.Time{}, errors.New("service expiry missing")
	}
	if string(raw) == "null" {
		return time.Time{}, nil
	}
	var value string
	if err := json.Unmarshal(raw, &value); err != nil || value == "" {
		return time.Time{}, errors.New("service expiry invalid")
	}
	expiresAt, err := time.Parse(time.RFC3339Nano, value)
	if err != nil {
		return time.Time{}, errors.New("service expiry invalid")
	}
	return expiresAt, nil
}

func validMobilePairingID(value string) bool {
	if len(value) < 16 || len(value) > 96 {
		return false
	}
	return validBase64URLSegment(value)
}

func validBase64URLSegment(value string) bool {
	if value == "" {
		return false
	}
	for _, character := range value {
		if !(character >= 'A' && character <= 'Z') &&
			!(character >= 'a' && character <= 'z') &&
			!(character >= '0' && character <= '9') &&
			character != '-' && character != '_' {
			return false
		}
	}
	return true
}
