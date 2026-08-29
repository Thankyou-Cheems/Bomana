package main

import (
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"strings"
	"testing"
	"time"
)

func TestVerifyMobileEnhancedLeaseAcceptsTrustedBoundLease(t *testing.T) {
	now := time.Date(2026, 8, 29, 12, 0, 0, 0, time.UTC)
	bridgePairingID := "bridge_pairing_1234567890"
	publicKey, privateKey := deterministicMobileLeaseTestKey()
	token := signedMobileLeaseForTest(t, privateKey, "test-key", bridgePairingID, now, nil)

	expiresAt, err := verifyMobileEnhancedLeaseWithKeys(token, bridgePairingID, now, func(keyID string) (ed25519.PublicKey, bool) {
		return publicKey, keyID == "test-key"
	})

	if err != nil {
		t.Fatal(err)
	}
	want := now.Add(7 * time.Hour)
	if !expiresAt.Equal(want) {
		t.Fatalf("verified expiry = %s, want %s", expiresAt, want)
	}
}

func TestVerifyMobileEnhancedLeaseRejectsInvalidAuthorization(t *testing.T) {
	now := time.Date(2026, 8, 29, 12, 0, 0, 0, time.UTC)
	bridgePairingID := "bridge_pairing_1234567890"
	publicKey, privateKey := deterministicMobileLeaseTestKey()
	trustedKeys := func(keyID string) (ed25519.PublicKey, bool) { return publicKey, keyID == "test-key" }
	tests := []struct {
		name        string
		verifyID    string
		keyID       string
		mutate      func(header map[string]any, claims map[string]any)
		tamper      bool
		resolveKeys mobileLeaseKeyResolver
	}{
		{name: "tampered signature", tamper: true},
		{name: "wrong pairing identity", verifyID: "bridge_pairing_0987654321"},
		{name: "wrong audience", mutate: func(_ map[string]any, claims map[string]any) { claims["aud"] = "bomana:web" }},
		{name: "wrong token type", mutate: func(header map[string]any, _ map[string]any) { header["typ"] = "bomana-web-access+jwt" }},
		{name: "wrong feature", mutate: func(_ map[string]any, claims map[string]any) { claims["required_feature"] = "bomana.standard" }},
		{name: "unknown key", keyID: "unknown-key"},
		{name: "expired", mutate: func(_ map[string]any, claims map[string]any) {
			claims["iat"] = now.Add(-time.Hour).Unix()
			claims["exp"] = now.Add(-time.Second).Unix()
		}},
		{name: "duration exceeds eight hours", mutate: func(_ map[string]any, claims map[string]any) {
			claims["iat"] = now.Add(-time.Minute).Unix()
			claims["exp"] = now.Add(8*time.Hour - time.Minute + time.Second).Unix()
		}},
		{name: "issued too far in future", mutate: func(_ map[string]any, claims map[string]any) {
			claims["iat"] = now.Add(mobileLeaseClockSkew + time.Second).Unix()
			claims["exp"] = now.Add(time.Hour).Unix()
		}},
		{name: "service expires first", mutate: func(_ map[string]any, claims map[string]any) {
			claims["service_expires_at"] = now.Add(time.Hour).Format(time.RFC3339Nano)
		}},
		{name: "missing entitlement version", mutate: func(_ map[string]any, claims map[string]any) {
			delete(claims, "entitlement_version")
		}},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			verifyID := test.verifyID
			if verifyID == "" {
				verifyID = bridgePairingID
			}
			keyID := test.keyID
			if keyID == "" {
				keyID = "test-key"
			}
			token := signedMobileLeaseForTest(t, privateKey, keyID, bridgePairingID, now, test.mutate)
			if test.tamper {
				token = tamperMobileLeaseSignature(t, token)
			}
			resolveKeys := test.resolveKeys
			if resolveKeys == nil {
				resolveKeys = trustedKeys
			}
			if _, err := verifyMobileEnhancedLeaseWithKeys(token, verifyID, now, resolveKeys); err == nil {
				t.Fatal("invalid mobile lease was accepted")
			}
		})
	}
}

func TestProductionMobileLeasePublicKeyMatchesPublishedSPKI(t *testing.T) {
	key, trusted := productionMobileLeaseKey(mobileLeaseProductionKeyID)
	if !trusted || len(key) != ed25519.PublicKeySize {
		t.Fatalf("production mobile lease key unavailable: trusted=%v length=%d", trusted, len(key))
	}
	if _, trusted := productionMobileLeaseKey("retired-key"); trusted {
		t.Fatal("unknown mobile lease key was trusted")
	}
}

func deterministicMobileLeaseTestKey() (ed25519.PublicKey, ed25519.PrivateKey) {
	seed := sha256.Sum256([]byte("bomana-mobile-lease-test-key"))
	privateKey := ed25519.NewKeyFromSeed(seed[:])
	return privateKey.Public().(ed25519.PublicKey), privateKey
}

func signedMobileLeaseForTest(
	t *testing.T,
	privateKey ed25519.PrivateKey,
	keyID string,
	bridgePairingID string,
	now time.Time,
	mutate func(header map[string]any, claims map[string]any),
) string {
	t.Helper()
	header := map[string]any{"alg": "EdDSA", "kid": keyID, "typ": mobileLeaseType}
	claims := map[string]any{
		"iss":                 mobileLeaseIssuer,
		"aud":                 mobileLeaseAudience,
		"sub":                 "user-1",
		"jti":                 "mobile-lease-1",
		"app_id":              mobileLeaseApplication,
		"required_feature":    mobileLeaseFeature,
		"bridge_pairing_id":   bridgePairingID,
		"iat":                 now.Add(-time.Minute).Unix(),
		"exp":                 now.Add(7 * time.Hour).Unix(),
		"service_expires_at":  now.Add(8 * time.Hour).Format(time.RFC3339Nano),
		"entitlement_version": int64(5),
	}
	if mutate != nil {
		mutate(header, claims)
	}
	headerJSON, err := json.Marshal(header)
	if err != nil {
		t.Fatal(err)
	}
	claimsJSON, err := json.Marshal(claims)
	if err != nil {
		t.Fatal(err)
	}
	headerSegment := base64.RawURLEncoding.EncodeToString(headerJSON)
	claimsSegment := base64.RawURLEncoding.EncodeToString(claimsJSON)
	signed := headerSegment + "." + claimsSegment
	signature := ed25519.Sign(privateKey, []byte(signed))
	return signed + "." + base64.RawURLEncoding.EncodeToString(signature)
}

func tamperMobileLeaseSignature(t *testing.T, token string) string {
	t.Helper()
	segments := strings.Split(token, ".")
	if len(segments) != 3 {
		t.Fatal("test mobile lease malformed")
	}
	signature, err := base64.RawURLEncoding.DecodeString(segments[2])
	if err != nil {
		t.Fatal(err)
	}
	signature[0] ^= 0xff
	segments[2] = base64.RawURLEncoding.EncodeToString(signature)
	return strings.Join(segments, ".")
}
